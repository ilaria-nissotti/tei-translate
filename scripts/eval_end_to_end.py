"""Question 3 of the evaluation: translation and tags together, end to end, on the gold set.

Runs the real pipeline (MT engine + aligner) on the Greek source of each gold
file and compares its English TEI with the gold English TEI:

    python scripts/eval_end_to_end.py --max-files 3 --max-blocks 40                 # madlad-3b + ugarit, hybrid vs span-wise
    python scripts/eval_end_to_end.py --conditions plain hybrid spanwise --comet    # also the no-tags upper bound and COMET
    python scripts/eval_end_to_end.py --engine identity --aligner monotone          # quick check without models

Conditions: hybrid (the pipeline's default), spanwise (every text piece
translated where it is), plain (the text without tags: upper bound for
translation quality). Scores: validator pass rate, structure match, chrF /
BLEU / COMET on the text, and Node-chrF (right words inside the right tags).
How it works: src/tei_translate/metrics/end_to_end.py.

Translating whole works with a big model on a CPU takes hours (MADLAD: about
5.5 Greek words per second), so --max-files and --max-blocks (first N text
blocks of each file) choose a subset; every condition uses the same subset.
Model engines and aligners need pip install -e .[mt]; --comet needs .[comet].

Writes to outputs/eval_end_to_end/<timestamp>/ (or --out):
- report.md          the scores per condition, per file, and why blocks went span-wise
- units.jsonl        one line per scored block: Greek, gold and each condition's output
- summary.json       the numbers of report.md
- run.json           settings
- hybrid/, spanwise/ the English TEI files; greek/ the truncated Greek input (with --max-blocks)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from tei_translate.align import get_aligner
from tei_translate.engines import get_engine
from tei_translate.metrics.comet_score import DEFAULT_MODEL
from tei_translate.metrics.end_to_end import CONDITIONS, TAGGED, evaluate_file, summarise
from tei_translate.metrics.placement_eval import (
    DEFAULT_GOLD_DIR, DEFAULT_PERSEUS_DIR, DEFAULT_RAW_DIR, load_index, load_policy,
)
from tei_translate.pipeline.document import load_pair

REPO_ROOT = Path(__file__).resolve().parents[1]

DESCRIPTIONS = {
    "plain": "the text of each block without tags, translated as one segment (upper bound for translation quality)",
    "hybrid": "the pipeline's default: whole sentences translated, tags put back with the aligner",
    "spanwise": "every text piece between tags translated on its own; tags never move",
}


def number(value, digits=1):
    """A number with a fixed number of decimals; None -> '-'."""
    return "-" if value is None else f"{value:.{digits}f}"


def percent(value):
    """0.857 -> '85.7%'; None -> '-'."""
    return "-" if value is None else f"{100 * value:.1f}%"


def overview_table(summaries):
    """One row per condition."""
    lines = ["| condition | blocks | files passing the validator | structure match | chrF | BLEU | COMET | "
             "Node-chrF | time (s) |", "|---|---|---|---|---|---|---|---|---|"]
    for condition, s in summaries.items():
        valid = f"{s['files_valid']} of {s['files']}" if condition in TAGGED else "-"
        lines.append(f"| {condition} | {s['blocks']} | {valid} | {percent(s.get('structure_match'))} | "
                     f"{number(s['chrf'])} | {number(s['bleu'])} | {number(s['comet'], 3)} | "
                     f"{number(s.get('node_chrf'))} | {number(s['seconds'], 0)} |")
    return lines


def per_file_table(summaries, field, digits=1):
    """One row per gold file, one column per condition, for one score."""
    conditions = [c for c, s in summaries.items() if any(field in part for part in s["per_file"].values())]
    if not conditions:
        return []
    files = list(next(iter(summaries.values()))["per_file"])
    lines = ["| gold file | blocks | " + " | ".join(conditions) + " |", "|---|---|" + "---|" * len(conditions)]
    for name in files:
        blocks = next(iter(summaries.values()))["per_file"][name]["blocks"]
        cells = [number(summaries[c]["per_file"][name].get(field), digits) for c in conditions]
        lines.append(f"| {name} | {blocks} | " + " | ".join(cells) + " |")
    return lines


def most_frequent_first(reason_and_count):
    """Sort key for (reason, count) pairs: highest count first, then alphabetical."""
    reason, count = reason_and_count
    return -count, reason


def hybrid_lines(summaries):
    """How many blocks the hybrid pipeline placed, and why the others went span-wise."""
    s = summaries.get("hybrid")
    if not s:
        return []
    lines = [f"Blocks placed by the hybrid method: {s['blocks_placed']}; translated span-wise instead: "
             f"{s['blocks_spanwise']} (over the whole translated files, not only the scored blocks)."]
    if s["spanwise_reasons"]:
        reasons = sorted(s["spanwise_reasons"].items(), key=most_frequent_first)
        lines.append("Reasons: " + ", ".join(f"`{reason}` ({count})" for reason, count in reasons) + ".")
    return lines


def validator_lines(summaries):
    """Which validator checks failed, per tagged condition."""
    lines = []
    for condition, s in summaries.items():
        if condition in TAGGED:
            failed = ", ".join(f"{name} ({count} files)" for name, count in sorted(s["failed_checks"].items()))
            lines.append(f"- **{condition}**: {failed or 'all checks passed in every file'}")
    return lines


def report_markdown(summaries, settings, errors):
    """The whole report as Markdown text."""
    lines = [
        "# End-to-end evaluation on the gold set",
        "",
        f"Engine `{settings['engine']}`, aligner `{settings['aligner']}`. Gold set `{settings['gold_dir']}`: "
        f"{len(settings['files'])} file(s)"
        + (f", first {settings['max_blocks']} text blocks of each" if settings["max_blocks"] else "")
        + f". Date: {settings['date']}.",
        "",
        "The pipeline translates the Greek source of each gold file; its English TEI is compared with the gold "
        "English TEI block by block (Greek, gold and output blocks paired by position). Every condition is scored "
        "on the same blocks: those the hybrid pipeline handles, where the gold block is translated. Notes and "
        "references count as points (their content is left out), xml:lang is ignored.",
        "",
        "## Conditions",
        "",
        *[f"- **{c}**: {DESCRIPTIONS[c]}" for c in summaries],
        "",
        "## Scores",
        "",
        "- **files passing the validator**: every check of the pipeline's validator passes (well-formed, same "
        "structure as the Greek, citation numbers kept, kept elements unchanged, header unchanged);",
        "- **structure match**: share of blocks with exactly the gold's tags (elements, attributes, nesting);",
        "- **chrF / BLEU / COMET**: the text without tags, against the gold English (one reference);",
        "- **Node-chrF**: chrF inside each element, elements paired by tag and attributes; low if the words are "
        "in the wrong tags or the translation is poor.",
        "",
        *overview_table(summaries),
        "",
        "## Hybrid placement",
        "",
        *(hybrid_lines(summaries) or ["(hybrid not run)"]),
        "",
        "## Validator",
        "",
        *(validator_lines(summaries) or ["- (no tagged condition run)"]),
        "",
        "## chrF per gold file",
        "",
        *per_file_table(summaries, "chrf"),
        "",
        "## Node-chrF per gold file",
        "",
        *(per_file_table(summaries, "node_chrf") or ["(no tagged condition run)"]),
        "",
    ]
    if errors:
        lines += ["## Files not scored", "", *[f"- `{name}`: {error}" for name, error in errors.items()], ""]
    return "\n".join(lines)


def matches(gold_file, name):
    """True if name picks out this gold file: one of its dot-separated parts ('tlg006'), or the
    beginning of its name ('tlg0062.tlg006'). Plain substring matching is not enough: 'tlg006'
    is inside 'tlg0062', the text group of every Lucian file."""
    return name in gold_file.split(".") or gold_file.startswith(name + ".") or gold_file == name


def choose_files(files, names, max_files):
    """The gold files to use: those matched by one of names (all if none given), at most max_files."""
    if names:
        files = [entry for entry in files if any(matches(entry["gold_file"], name) for name in names)]
    return files[:max_files] if max_files else files


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="End-to-end evaluation of the pipeline on the gold set.")
    parser.add_argument("--engine", default="madlad-3b", help="MT engine (default madlad-3b)")
    parser.add_argument("--aligner", default="ugarit", help="aligner for hybrid placement (default ugarit)")
    parser.add_argument("--conditions", nargs="+", choices=CONDITIONS, default=["hybrid", "spanwise"],
                        help="what to compare (default: hybrid spanwise)")
    parser.add_argument("--files", nargs="+", help="only gold files whose name contains one of these (e.g. tlg001)")
    parser.add_argument("--max-files", type=int, help="use at most this many gold files")
    parser.add_argument("--max-blocks", type=int, help="translate only the first N text blocks of each file")
    parser.add_argument("--comet", action="store_true", help="also compute COMET (needs pip install -e .[comet])")
    parser.add_argument("--comet-model", default=DEFAULT_MODEL)
    parser.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD_DIR)
    parser.add_argument("--perseus", type=Path, default=DEFAULT_PERSEUS_DIR)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--out", type=Path, help="output folder (default: outputs/eval_end_to_end/<timestamp>)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not (args.gold_dir / "translations.csv").exists():
        print(f"no translations.csv in {args.gold_dir}")
        return 1
    files = choose_files(load_index(args.gold_dir, args.perseus, args.raw), args.files, args.max_files)
    if not files:
        print("no gold file matches")
        return 1
    policy = load_policy(as_wrap=False)          # the pipeline's own policy: this is the real output
    pair = load_pair()
    engine = get_engine(args.engine)
    aligner = get_aligner(args.aligner)
    out = args.out or REPO_ROOT / "outputs" / "eval_end_to_end" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)

    start = time.time()
    file_results, errors = [], {}
    for number_, entry in enumerate(files, 1):
        print(f"[{number_}/{len(files)}] {entry['gold_file']}", flush=True)
        result = evaluate_file(entry, engine, aligner, policy, pair, args.conditions, args.max_blocks, out)
        if "error" in result:
            errors[entry["gold_file"]] = result["error"]
        file_results.append(result)
    summaries = {condition: summarise(file_results, condition, args.comet, args.comet_model)
                 for condition in args.conditions}
    settings = {"engine": engine.name, "aligner": aligner.name, "conditions": args.conditions,
                "gold_dir": str(args.gold_dir), "files": [entry["gold_file"] for entry in files],
                "max_blocks": args.max_blocks, "comet": args.comet, "comet_model": args.comet_model,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "seconds": round(time.time() - start, 1)}

    with open(out / "units.jsonl", "w", encoding="utf-8") as f:
        for result in file_results:
            for i, unit in enumerate(result.get("units", [])):
                row = {"gold_file": result["gold_file"], "citation": unit["citation"], "index": unit["index"],
                       "source": unit["source"], "reference": unit["reference"]}
                for condition, entry in result["conditions"].items():
                    row[condition] = entry["hyps"][i]
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary_data = {condition: {key: value for key, value in s.items() if key != "block_comet"}
                    for condition, s in summaries.items()}
    (out / "summary.json").write_text(json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "run.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    report = report_markdown(summaries, settings, errors)
    (out / "report.md").write_text(report, encoding="utf-8")

    print(report)
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
