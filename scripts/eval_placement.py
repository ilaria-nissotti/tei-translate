"""Score the hybrid pipeline's tag placement against the gold set, for one or more aligners.

    python scripts/eval_placement.py                                  # the baselines none, monotone, sentence (no models)
    python scripts/eval_placement.py --aligners none monotone sentence xlmr ugarit
    python scripts/eval_placement.py --gold-dir tests/fixtures/placement_eval/gold

The gold set is the folder data/gold/grc-en/ (gold .en.xml files and their
index translations.csv; see docs/gold_set_handover.md). The Greek source of
each gold file is read from data/perseus/ or, if that is missing, from the
local Perseus clone data/raw/canonical-greekLit/. The model aligners (ugarit,
xlmr) need: pip install -e .[mt]. dragoman is left out of the evaluation for
now: its tokenizer does not load with the installed Transformers version
(AttributeError: 'list' object has no attribute 'keys'), so almost every
block would be an aligner error. How the evaluation works is described in
src/tei_translate/metrics/placement_eval.py.

Writes to outputs/eval_placement/<timestamp>/ (or --out):
- report.md     tag accuracy, average distance and fallback rate per aligner;
                accuracy per tag type, per sentence mode and per gold file
- results.jsonl one line per (aligner, block): status, scores, the rebuilt block
- summary.json  the numbers of report.md
- run.json      settings: gold folder, files, aligners, policy
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from tei_translate.metrics.placement_eval import (
    BASELINES, DEFAULT_GOLD_DIR, DEFAULT_PERSEUS_DIR, DEFAULT_RAW_DIR, evaluate, load_index, load_policy,
    make_method,
)

# Short descriptions of the model aligners, for the report.
ALIGNERS = {
    "ugarit": "UGARIT/grc-alignment: XLM-RoBERTa further trained on Ancient Greek and fine-tuned for Greek alignment",
    "xlmr": "xlm-roberta-base: the same kind of model without Ancient Greek training",
}

REPO_ROOT = Path(__file__).resolve().parents[1]

MODES = {
    "paired": "same number of sentences, paired one to one",
    "grouped": "more English sentences, grouped per Greek sentence",
    "whole": "fewer English sentences, whole block as one unit",
}


def percent(value):
    """0.857 -> '85.7%'; None -> '-'."""
    return "-" if value is None else f"{100 * value:.1f}%"


def number(value, digits=1):
    """A number with a fixed number of decimals; None -> '-'."""
    return "-" if value is None else f"{value:.{digits}f}"


def overview_table(runs):
    """One row per aligner: strict accuracy (the headline) first, then the numbers on the blocks it could place."""
    lines = ["| aligner | **strict accuracy** (all gold tags) | fallback rate | blocks placed | tags in placed blocks | "
             "tag accuracy (placed blocks only) | average distance (chars, placed blocks) | text differs | other |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, run in runs.items():
        s = run["summary"]
        st = s["statuses"]
        placeable = st.get("scored", 0) + st.get("fallback", 0) + st.get("text_differs", 0) + st.get("aligner_error", 0)
        other = ", ".join(f"{k} {v}" for k, v in sorted(st.items())
                          if k not in ("scored", "fallback", "text_differs")) or "-"
        lines.append(f"| {name} | **{percent(s['strict_accuracy'])}** ({s['correct']} of {s['all_tags']}) | "
                     f"{percent(s['fallback_rate'])} | {s['blocks']} of {placeable} | {s['tags']} of {s['all_tags']} | "
                     f"{percent(s['tag_accuracy'])} | {number(s['average_distance'])} | "
                     f"{st.get('text_differs', 0)} | {other} |")
    return lines


def breakdown_table(runs, field, label, describe=None):
    """Tag accuracy per value of a summary breakdown (per_tag, by_mode or by_file), one column per aligner."""
    values = sorted({value for run in runs.values() for value in run["summary"][field]})
    lines = [f"| {label} | " + " | ".join(runs) + " |", "|---|" + "---|" * len(runs)]
    for value in values:
        cells = []
        for run in runs.values():
            group = run["summary"][field].get(value)
            if not group:
                cells.append("-")
            elif field == "per_tag":
                cells.append(f"{percent(group['correct'] / group['total'])} ({group['total']})")
            else:
                cells.append(f"{percent(group['tag_accuracy'])} ({group['blocks']} blocks, {group['tags']} tags)")
        name = f"`{value}`" if field == "per_tag" else value
        if describe and value in describe:
            name = f"{value}: {describe[value]}"
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return lines


def most_frequent_first(reason_and_count):
    """Sort key for (reason, count) pairs: highest count first, then alphabetical."""
    reason, count = reason_and_count
    return -count, reason


def fallback_lines(runs):
    """Why blocks could not be placed (they would go span-wise), per aligner."""
    lines = []
    for name, run in runs.items():
        reasons = run["summary"]["fallback_reasons"]
        if reasons:
            listed = ", ".join(f"`{reason}` ({count})" for reason, count in sorted(reasons.items(), key=most_frequent_first))
            lines.append(f"- **{name}**: {listed}")
    return lines or ["- none"]


def method_lines(runs):
    """One line per compared method, saying what it is."""
    lines = []
    for name in runs:
        description = BASELINES.get(name) or ALIGNERS.get(name) or "word aligner"
        kind = "baseline" if name in BASELINES else "aligner"
        lines.append(f"- **{name}** ({kind}): {description}")
    return lines


def report_markdown(runs, settings):
    """The whole report as Markdown text."""
    files = ", ".join(f"`{name}`" for name in settings["files"])
    lines = [
        "# Tag placement against the gold set",
        "",
        f"Gold set: `{settings['gold_dir']}`: {len(settings['files'])} file(s) ({files}). Date: {settings['date']}.",
        "",
        "Each Greek text block is paired with the gold block in the same position; the pipeline places the Greek "
        "block's tags into the gold English text, and the result is compared with the gold tags.",
        "",
        "- **Strict accuracy (headline)** = gold tags at exactly the right position / all gold tags of all "
        "placeable blocks. Tags in blocks a method could not place (it would fall back to span-wise translation) "
        "count as wrong, so every method is measured on the same tags. Use this number to compare methods.",
        "- **Tag accuracy (placed blocks only)** = the same, but only over the blocks the method could place. "
        "Each method is scored on a different set of blocks (a method that gives up on hard blocks looks better), "
        "so this number does not compare methods.",
        "- **Average distance** = how many characters off the tags in the placed blocks are.",
        "",
        "Scoring rules: positions are counted without spaces"
        + (" and without punctuation (a tag on either side of a space, quotation mark, comma or full stop is at "
           "the same place)" if settings["ignore_punctuation"] else " (a tag on either side of a space is at the "
           "same place; punctuation counts)")
        + "; an opening and a closing tag count as two tags; notes and references count as single points (their "
        "content is not compared); fixed elements (label, term, ...) are scored before their replacement "
        f"({'on' if settings['fixed_as_wrap'] else 'off'}).",
        "",
        "## Methods compared",
        "",
        *method_lines(runs),
        "",
        "## Overview",
        "",
        *overview_table(runs),
        "",
        "## Tag accuracy per tag type (number of gold tags in brackets)",
        "",
        *breakdown_table(runs, "per_tag", "tag"),
        "",
        "## Tag accuracy per sentence mode",
        "",
        "How the gold English sentences were matched to the Greek sentences (the pipeline places tags sentence by sentence).",
        "",
        *breakdown_table(runs, "by_mode", "mode", MODES),
        "",
        "## Tag accuracy per gold file",
        "",
        *breakdown_table(runs, "by_file", "gold file"),
        "",
        "## Why blocks could not be placed",
        "",
        *fallback_lines(runs),
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Score hybrid tag placement against the gold set.")
    parser.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD_DIR,
                        help="gold folder with translations.csv and the .en.xml files")
    parser.add_argument("--perseus", type=Path, default=DEFAULT_PERSEUS_DIR, help="data/perseus folder")
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW_DIR, help="local Perseus clone, used if --perseus is missing")
    parser.add_argument("--aligners", nargs="+", default=["none", "monotone", "sentence"],
                        help="methods to compare: baselines none, monotone, sentence; "
                             "aligners ugarit, xlmr, embed:<model> (dragoman is left out of the evaluation: "
                             "its tokenizer does not load with the installed Transformers version)")
    parser.add_argument("--policy-as-is", action="store_true",
                        help="use the pipeline policy unchanged (fixed elements such as label/term/foreign are then "
                             "replaced by their transliteration or Greek and usually cannot be scored)")
    parser.add_argument("--keep-punctuation", action="store_true",
                        help="count punctuation when comparing positions (by default a tag on either side of a "
                             "quotation mark, comma or full stop counts as the same place)")
    parser.add_argument("--out", type=Path, help="output folder (default: outputs/eval_placement/<timestamp>)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not (args.gold_dir / "translations.csv").exists():
        print(f"no translations.csv in {args.gold_dir}")
        return 1
    files = load_index(args.gold_dir, args.perseus, args.raw)
    policy = load_policy(as_wrap=not args.policy_as_is)
    aligners, policies = {}, {}
    for name in args.aligners:
        aligners[name], policies[name] = make_method(name, as_wrap=not args.policy_as_is)

    start = time.time()
    runs = evaluate(files, aligners, policy, policies, ignore_punctuation=not args.keep_punctuation)
    settings = {
        "gold_dir": str(args.gold_dir), "files": [entry["gold_file"] for entry in files],
        "aligners": args.aligners, "fixed_as_wrap": not args.policy_as_is,
        "ignore_punctuation": not args.keep_punctuation,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "seconds": round(time.time() - start, 1),
    }

    out = args.out or REPO_ROOT / "outputs" / "eval_placement" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "results.jsonl", "w", encoding="utf-8") as f:
        for name, run in runs.items():
            for result in run["results"]:
                f.write(json.dumps({"aligner": name, **result}, ensure_ascii=False) + "\n")
    summaries = {name: run["summary"] for name, run in runs.items()}
    (out / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "run.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    report = report_markdown(runs, settings)
    (out / "report.md").write_text(report, encoding="utf-8")

    print(report)
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
