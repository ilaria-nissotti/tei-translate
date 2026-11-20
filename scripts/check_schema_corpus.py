"""Run the pipeline on every Greek Perseus file and record the TEI schema check.

Uses the identity engine and the monotone aligner (no model), so it measures what
the pipeline itself does to schema validity, not the translation. For each file:
is the source valid against tei_all, is the output, and do all checks pass.

    python scripts/check_schema_corpus.py [--every K] [--limit N]

Needs the Perseus clone (python scripts/data/count_tags.py) in data/raw/canonical-greekLit/.
Writes outputs/schema/<timestamp>.csv and prints a summary.
"""

from __future__ import annotations

import argparse
import csv
import time
from collections import Counter
from pathlib import Path

from lxml import etree

from tei_translate.pipeline.document import translate_document
from tei_translate.pipeline.validate import schema_errors

ROOT = Path(__file__).resolve().parents[1]
PERSEUS = ROOT / "data" / "raw" / "canonical-greekLit" / "data"
CHECK = "TEI schema (tei_all)"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--every", type=int, default=1, help="keep every K-th file")
    ap.add_argument("--limit", type=int, default=0, help="stop after N files (0 = all)")
    args = ap.parse_args()

    files = sorted(PERSEUS.glob("*/*/*-grc*.xml"))[:: args.every]
    if args.limit:
        files = files[: args.limit]
    if not files:
        raise SystemExit(f"no Greek files under {PERSEUS}; run scripts/data/count_tags.py first")

    out_dir = ROOT / "outputs" / "schema"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}.csv"

    summary, new_errors = Counter(), Counter()
    start = time.time()
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file", "source_valid", "source_errors", "schema_ok", "schema_detail", "failed_checks"])
        for i, path in enumerate(files, 1):
            rel = path.relative_to(PERSEUS).as_posix()
            try:
                src_err = schema_errors(etree.parse(str(path)))
                result = translate_document(path, engine="identity", aligner="monotone")
            except Exception as e:  # noqa: BLE001 - one broken file must not stop the run
                writer.writerow([rel, "", "", "", f"error: {e}", ""])
                summary["pipeline error"] += 1
                continue
            checks = result.report.checks
            schema = checks.get(CHECK, {"ok": False, "detail": "not run"})
            failed = [k for k, v in checks.items() if not v["ok"]]
            writer.writerow([rel, not src_err, len(src_err), schema["ok"], schema["detail"], ";".join(failed)])
            summary["source valid" if not src_err else "source invalid"] += 1
            if not schema["ok"]:
                summary["new schema errors"] += 1
                new_errors[schema["detail"].split("first: ", 1)[-1].split(": ", 1)[-1]] += 1
            summary["all checks pass" if not failed else "some check fails"] += 1
            if i % 50 == 0:
                print(f"{i}/{len(files)} files, {time.time() - start:.0f} s", flush=True)

    print(f"\n{len(files)} files in {time.time() - start:.0f} s -> {out_path.relative_to(ROOT)}")
    for k, v in sorted(summary.items()):
        print(f"  {k}: {v}")
    if new_errors:
        print("first new schema error per failing file:")
        for msg, n in new_errors.most_common(10):
            print(f"  {n:4d}  {msg}")


if __name__ == "__main__":
    main()
