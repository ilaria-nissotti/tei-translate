"""Score the hybrid pipeline's tag placement against the gold set, for one or more aligners.

    python scripts/eval_placement.py                                  # aligners none and monotone (no models)
    python scripts/eval_placement.py --aligners ugarit dragoman monotone none
    python scripts/eval_placement.py --gold path/to/gold.jsonl --out outputs/eval_placement/my_run

The model aligners (ugarit, dragoman, xlmr) need: pip install -e .[mt].
The gold set and its format are described in docs/gold_set_handover.md; the
evaluation itself in src/tei_translate/metrics/placement_eval.py.

Writes to outputs/eval_placement/<timestamp>/ (or --out):
- report.md     tag accuracy, average distance and fallback rate per aligner,
                accuracy per tag type and per text type
- results.jsonl one line per (aligner, gold item): status, scores, the output block
- summary.json  the numbers of report.md
- run.json      settings: gold file, aligners, policy, number of items
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from tei_translate.align import get_aligner
from tei_translate.metrics.placement_eval import evaluate, load_gold, load_policy
from tei_translate.pipeline.document import load_pair

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = REPO_ROOT / "data" / "gold" / "grc-en" / "gold.jsonl"


def percent(value):
    """0.857 -> '85.7%'; None -> '-'."""
    return "-" if value is None else f"{100 * value:.1f}%"


def number(value, digits=2):
    """A number with a fixed number of decimals; None -> '-'."""
    return "-" if value is None else f"{value:.{digits}f}"


def overview_table(runs):
    """One row per aligner: blocks, tag accuracy, average distance, fallback rate and the other statuses."""
    lines = ["| aligner | blocks scored | tags | tag accuracy | average distance (chars) | fallback rate | text differs | split mismatch |",
             "|---|---|---|---|---|---|---|---|"]
    for name, run in runs.items():
        s = run["summary"]
        st = s["statuses"]
        lines.append(f"| {name} | {s['blocks']} of {s['items']} | {s['tags']} | {percent(s['tag_accuracy'])} | "
                     f"{number(s['average_distance'])} | {percent(s['fallback_rate'])} | "
                     f"{st.get('text_differs', 0)} | {st.get('split_mismatch', 0)} |")
    return lines


def per_tag_table(runs):
    """Tag accuracy per tag type (rows) and aligner (columns), with the number of gold tags."""
    names = sorted({tag for run in runs.values() for tag in run["summary"]["per_tag"]})
    lines = ["| tag | " + " | ".join(runs) + " |", "|---|" + "---|" * len(runs)]
    for tag in names:
        cells = []
        for run in runs.values():
            counts = run["summary"]["per_tag"].get(tag)
            cells.append("-" if not counts else f"{percent(counts['correct'] / counts['total'])} ({counts['total']})")
        lines.append(f"| `{tag}` | " + " | ".join(cells) + " |")
    return lines


def per_type_table(runs):
    """Tag accuracy per text type (prose, poetry, drama) and aligner."""
    types = sorted({t for run in runs.values() for t in run["summary"]["by_type"]})
    lines = ["| text type | " + " | ".join(runs) + " |", "|---|" + "---|" * len(runs)]
    for text_type in types:
        cells = []
        for run in runs.values():
            group = run["summary"]["by_type"].get(text_type)
            cells.append("-" if not group else f"{percent(group['tag_accuracy'])} ({group['tags']} tags)")
        lines.append(f"| {text_type} | " + " | ".join(cells) + " |")
    return lines


def most_frequent_first(reason_and_count):
    """Sort key for (reason, count) pairs: highest count first, then alphabetical."""
    reason, count = reason_and_count
    return -count, reason


def fallback_lines(runs):
    """Why blocks fell back to span-wise translation, per aligner."""
    lines = []
    for name, run in runs.items():
        reasons = run["summary"]["fallback_reasons"]
        if reasons:
            listed = ", ".join(f"`{reason}` ({count})" for reason, count in sorted(reasons.items(), key=most_frequent_first))
            lines.append(f"- **{name}**: {listed}")
    return lines or ["- none"]


def report_markdown(runs, settings):
    """The whole report as Markdown text."""
    lines = [
        "# Tag placement against the gold set",
        "",
        f"Gold set: `{settings['gold']}` ({settings['items']} items). Date: {settings['date']}. "
        f"Fixed elements (names, numbers, ...) scored before their replacement: {settings['fixed_as_wrap']}.",
        "",
        "Tag accuracy = gold tags placed at exactly the right character position / all gold tags in the scored blocks. "
        "Average distance = how many characters off the tags are. A block that fell back to span-wise translation "
        "has no placement score; it counts in the fallback rate.",
        "",
        "## Overview",
        "",
        *overview_table(runs),
        "",
        "## Tag accuracy per tag type (number of gold tags in brackets)",
        "",
        *per_tag_table(runs),
        "",
        "## Tag accuracy per text type",
        "",
        *per_type_table(runs),
        "",
        "## Why blocks fell back to span-wise translation",
        "",
        *fallback_lines(runs),
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Score hybrid tag placement against the gold set.")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD, help="gold set (JSON lines)")
    parser.add_argument("--aligners", nargs="+", default=["none", "monotone"],
                        help="aligners to compare (none, monotone, ugarit, dragoman, xlmr, embed:<model>)")
    parser.add_argument("--policy-as-is", action="store_true",
                        help="use the pipeline policy unchanged (names etc. are then replaced and usually cannot be scored)")
    parser.add_argument("--out", type=Path, help="output folder (default: outputs/eval_placement/<timestamp>)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not args.gold.exists():
        print(f"gold set not found: {args.gold}")
        return 1
    items = load_gold(args.gold)
    policy = load_policy(as_wrap=not args.policy_as_is)
    aligners = {name: get_aligner(name) for name in args.aligners}

    start = time.time()
    runs = evaluate(items, aligners, policy, load_pair())
    settings = {
        "gold": str(args.gold), "items": len(items), "aligners": args.aligners,
        "fixed_as_wrap": not args.policy_as_is, "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "seconds": round(time.time() - start, 1),
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
