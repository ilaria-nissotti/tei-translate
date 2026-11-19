#!/usr/bin/env python3
"""
Create work_types.csv by reading the CONTENT of the Greek XML files
(not by guessing from the author).

Each work is classified as "poetry", "prose" or "drama" from the TEI markup
of its Greek text:

  1. Verse share: what fraction of the text sits inside verse-line <l>
     elements?  Prose works only quote verse occasionally (in this corpus
     never more than ~25%), while poetry and drama are ~90%+ verse.
        verse share <  0.35  ->  prose
  2. Speeches: of the verse works, plays are made of <sp> (speech) elements
     with <speaker> labels, poems are not.
        >= 10 speeches AND >= 0.05 speeches per verse line  ->  drama
        otherwise                                           ->  poetry

The Greek file is used because it is the original form of the work (a verse
work may have a prose English translation).  If a work has several Greek
editions, the largest one decides, and any disagreement is flagged in the
details file.

Run it AFTER build_dataset.py has downloaded the files:

    python make_work_types.py
    python make_work_types.py --dataset dataset --texts greek_english_texts.csv

Writes:
    <dataset>/work_types.csv          work_id, type
    <dataset>/work_type_details.csv   work_id, author, title, type, verse_share,
                                      speeches, verse_lines, characters,
                                      greek_files, editions_agree
Only the standard library is needed.
"""
import argparse
import csv
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

VERSE_SHARE_THRESHOLD = 0.35     # below this -> prose
MIN_SPEECHES_FOR_DRAMA = 10      # at least this many <sp> ...
SPEECHES_PER_LINE_FOR_DRAMA = 0.05  # ... and at least this many per verse line

_WS = re.compile(r"\s+")


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _chars(text: str) -> int:
    """Number of non-whitespace characters (ignores XML pretty-printing)."""
    return len(_WS.sub("", text))


def measure_file(path: Path) -> dict:
    """Measure verse share and speech count of one TEI XML file."""
    root = ET.parse(path).getroot()
    body = next((e for e in root.iter() if _local(e.tag) == "body"), None)
    if body is None:
        raise ValueError("no <body> element")

    total = _chars("".join(body.itertext()))
    verse_chars = verse_lines = speeches = 0
    stack = list(body)
    while stack:
        el = stack.pop()
        tag = _local(el.tag)
        if tag == "l":                       # verse line: count, don't descend
            verse_lines += 1
            verse_chars += _chars("".join(el.itertext()))
            continue
        if tag == "sp":
            speeches += 1
        stack.extend(el)

    share = verse_chars / total if total else 0.0
    return {"characters": total, "verse_lines": verse_lines,
            "verse_chars": verse_chars, "verse_share": share,
            "speeches": speeches}


def decide(m: dict) -> str:
    """Turn measurements into 'prose', 'poetry' or 'drama'."""
    if m["characters"] == 0:
        return "unknown"
    if m["verse_share"] < VERSE_SHARE_THRESHOLD:
        return "prose"
    lines = max(m["verse_lines"], 1)
    if (m["speeches"] >= MIN_SPEECHES_FOR_DRAMA
            and m["speeches"] / lines >= SPEECHES_PER_LINE_FOR_DRAMA):
        return "drama"
    return "poetry"


def classify_work(greek_paths: list[Path]) -> dict:
    """Classify one work from its Greek file(s)."""
    results = []
    for p in greek_paths:
        try:
            m = measure_file(p)
            m["type"] = decide(m)
            m["file"] = p.name
            results.append(m)
        except Exception as e:  # unreadable / malformed file
            print(f"  warning: could not read {p}: {e}", file=sys.stderr)
    if not results:
        return {"type": "unknown", "verse_share": "", "speeches": "",
                "verse_lines": "", "characters": "", "greek_files": "",
                "editions_agree": ""}
    main = max(results, key=lambda r: r["characters"])
    return {
        "type": main["type"],
        "verse_share": round(main["verse_share"], 4),
        "speeches": main["speeches"],
        "verse_lines": main["verse_lines"],
        "characters": main["characters"],
        "greek_files": "; ".join(r["file"] for r in results),
        "editions_agree": len({r["type"] for r in results}) == 1,
    }


def build_work_types(works: list[dict], dataset_dir: Path) -> dict:
    """Classify every work, write the two CSVs, return {work_id: type}."""
    details, types = [], {}
    for i, w in enumerate(works, 1):
        wid = w["work_id"]
        greek_dir = dataset_dir / "texts" / wid / "greek"
        paths = sorted(greek_dir.glob("*.xml")) if greek_dir.is_dir() else []
        info = classify_work(paths)
        types[wid] = info["type"]
        details.append({"work_id": wid, "author": w.get("author", ""),
                        "title": w.get("title", ""), **info})
        if i % 100 == 0 or i == len(works):
            print(f"  classified {i}/{len(works)}")

    dataset_dir.mkdir(parents=True, exist_ok=True)
    with open(dataset_dir / "work_types.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["work_id", "type"])
        for wid, t in types.items():
            wr.writerow([wid, t])
    cols = ["work_id", "author", "title", "type", "verse_share", "speeches",
            "verse_lines", "characters", "greek_files", "editions_agree"]
    with open(dataset_dir / "work_type_details.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        wr.writerows(details)

    counts = {}
    for t in types.values():
        counts[t] = counts.get(t, 0) + 1
    print(f"Wrote {dataset_dir / 'work_types.csv'} ({len(types)} works): "
          + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    disagree = [d["work_id"] for d in details if d["editions_agree"] is False]
    if disagree:
        print(f"Note: Greek editions disagree for {len(disagree)} work(s): "
              + ", ".join(disagree) + " (largest edition used)")
    if counts.get("unknown"):
        print(f"WARNING: {counts['unknown']} work(s) could not be classified "
              "(Greek file missing or unreadable). Run build_dataset.py first.")
    return types


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--texts", default=str(here / "greek_english_texts.csv"))
    ap.add_argument("--dataset", default=str(here / "dataset"),
                    help="dataset folder made by build_dataset.py "
                         "(default: a 'dataset' folder next to this script)")
    args = ap.parse_args()

    with open(args.texts, newline="", encoding="utf-8-sig") as f:
        works = list(csv.DictReader(f))
    types = build_work_types(works, Path(args.dataset).resolve())
    if "unknown" in types.values():
        sys.exit(1)


if __name__ == "__main__":
    main()
