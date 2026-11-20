"""Question 1 of the evaluation: how good is the translation? chrF, BLEU and COMET per MT engine.

Scores the translations of an earlier scripts/compare_engines.py run, so no
engine has to run again:

    python scripts/compare_engines.py --engines opus-grk-en madlad-3b pivot-grc-el-en   # makes outputs/compare/<run>
    python scripts/eval_translation.py --run outputs/compare/<run>                      # chrF, BLEU, COMET
    python scripts/eval_translation.py --run outputs/compare/<run> --no-comet           # only chrF and BLEU

References are the Perseus English translations (several where a work has
several). Text only: tags play no part here (that is question 2,
scripts/eval_placement.py, and question 3, scripts/eval_end_to_end.py).
COMET needs pip install -e .[comet] and downloads Unbabel/wmt22-comet-da
(~2.3 GB) the first time; on a CPU it takes a few seconds per passage.

Writes to outputs/eval_translation/<timestamp>/ (or --out):
- report.md     chrF, BLEU, COMET per engine, overall and per work
- scores.jsonl  one line per passage: work, ref, and each engine's COMET score
- summary.json  the numbers of report.md
- run.json      settings: run folder, engines, COMET model
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from tei_translate.metrics.comet_score import DEFAULT_MODEL
from tei_translate.metrics.translation_eval import load_run, score_engines, works_in_order

REPO_ROOT = Path(__file__).resolve().parents[1]


def number(value, digits=1):
    """A number with a fixed number of decimals; None -> '-'."""
    return "-" if value is None else f"{value:.{digits}f}"


def overview_table(results, models):
    """One row per engine: chrF, BLEU, COMET."""
    lines = ["| engine | model | chrF | BLEU | COMET |", "|---|---|---|---|---|"]
    for name, result in results.items():
        lines.append(f"| {name} | `{models.get(name, '?')}` | {number(result['chrf'])} | "
                     f"{number(result['bleu'])} | {number(result['comet'], 3)} |")
    return lines


def per_work_table(results, works, field, digits):
    """One row per work, one column per engine, for one metric."""
    lines = ["| work | n | " + " | ".join(results) + " |", "|---|---|" + "---|" * len(results)]
    for work, label in works.items():
        first = next(iter(results.values()))["per_work"][work]
        cells = [number(result["per_work"][work][field], digits) for result in results.values()]
        lines.append(f"| {label} | {first['passages']} | " + " | ".join(cells) + " |")
    return lines


def report_markdown(results, works, settings, models):
    """The whole report as Markdown text."""
    lines = [
        "# Translation quality per MT engine",
        "",
        f"Passages and translations: `{settings['run']}` ({settings['passages']} Perseus passages). "
        f"Date: {settings['date']}.",
        "",
        "- **chrF** and **BLEU** (0-100): corpus level, against all Perseus English translations of the passage.",
        f"- **COMET** (`{settings['comet_model']}`, usually 0-1): each passage against its best reference, then "
        "averaged. It also reads the Greek source; the model was not trained on Ancient Greek, so read it as a "
        "second opinion next to chrF." if settings["comet"] else "- **COMET**: not computed (--no-comet).",
        "",
        "Text only: tags are not part of this score.",
        "",
        "## Overview",
        "",
        *overview_table(results, models),
        "",
        "## chrF per work",
        "",
        *per_work_table(results, works, "chrf", 1),
        "",
    ]
    if settings["comet"]:
        lines += ["## COMET per work", "", *per_work_table(results, works, "comet", 3), ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Score MT engines with chrF, BLEU and COMET.")
    parser.add_argument("--run", type=Path, required=True,
                        help="an outputs/compare/<timestamp>/ folder of scripts/compare_engines.py")
    parser.add_argument("--engines", nargs="+", help="score only these engines (default: all in the run)")
    parser.add_argument("--no-comet", action="store_true", help="only chrF and BLEU (no model needed)")
    parser.add_argument("--comet-model", default=DEFAULT_MODEL, help=f"COMET model (default {DEFAULT_MODEL})")
    parser.add_argument("--batch-size", type=int, default=8, help="COMET batch size")
    parser.add_argument("--out", type=Path, help="output folder (default: outputs/eval_translation/<timestamp>)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not (args.run / "translations.jsonl").exists():
        print(f"no translations.jsonl in {args.run} (run scripts/compare_engines.py first)")
        return 1
    samples, hyps, meta = load_run(args.run)
    if args.engines:
        missing = [name for name in args.engines if name not in hyps]
        if missing:
            print(f"not in the run: {', '.join(missing)}; the run has {', '.join(hyps)}")
            return 1
        hyps = {name: hyps[name] for name in args.engines}
    models = {name: info.get("model", "?") for name, info in (meta.get("engines") or {}).items()}

    start = time.time()
    results = score_engines(samples, hyps, use_comet=not args.no_comet, comet_model=args.comet_model,
                            batch_size=args.batch_size)
    works = works_in_order(samples)
    settings = {"run": str(args.run), "passages": len(samples), "engines": list(hyps),
                "comet": not args.no_comet, "comet_model": args.comet_model,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "seconds": round(time.time() - start, 1)}

    out = args.out or REPO_ROOT / "outputs" / "eval_translation" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "scores.jsonl", "w", encoding="utf-8") as f:
        for i, sample in enumerate(samples):
            row = {"work": sample["work"], "ref": sample["ref"]}
            for name, result in results.items():
                row[f"{name} comet"] = result["per_passage_comet"][i] if result["per_passage_comet"] else None
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {name: {key: value for key, value in result.items() if key != "per_passage_comet"}
               for name, result in results.items()}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "run.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    report = report_markdown(results, works, settings, models)
    (out / "report.md").write_text(report, encoding="utf-8")

    print(report)
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
