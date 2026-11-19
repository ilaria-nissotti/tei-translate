#!/usr/bin/env python3
"""
Count TEI tags in the downloaded Perseus dataset (data/perseus/, built by
build_dataset.py). Based on count_tags.py, but reads the local files listed
in data/perseus/pairs.csv instead of cloning the whole Perseus repository.

Two counts are written (each file is counted once, even if it appears in
several pairs):
    data/stats/perseus_tag_frequencies_greek.csv   Greek files only
    data/stats/perseus_tag_frequencies_all.csv     Greek + English files

Columns:
    tag                 TEI tag name (no namespace)
    count               all occurrences inside <text>
    with_text           occurrences with text directly inside the tag
    files               number of files the tag appears in
    greek_script_share  share of that direct text written in Greek letters
    inline_share        share of occurrences inside a <p> or <l>

Usage:
    python scripts/data/count_perseus_tags.py
    python scripts/data/count_perseus_tags.py --perseus my_dataset
"""
import argparse
import csv
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Tags that hold a whole stretch of text: a tag found inside one of these
# sits in the middle of a sentence ("inline").
TEXT_BLOCKS = {"p", "l"}


def direct_text(elem):
    """Text written directly inside an element, not inside its children."""
    pieces = [elem.text or ""] + [child.tail or "" for child in elem]
    return " ".join("".join(pieces).split())


def is_greek_letter(char):
    """True for Greek and Coptic (U+0370-03FF) and Greek Extended (U+1F00-1FFF)."""
    return "Ͱ" <= char <= "Ͽ" or "ἀ" <= char <= "῿"


class TagCounts:
    """Tag statistics over a set of files."""

    def __init__(self):
        self.count = Counter()
        self.with_text = Counter()
        self.files = Counter()
        self.inline = Counter()
        self.letters = Counter()
        self.greek_letters = Counter()
        self.n_files = 0

    def add_file(self, text_elem):
        self.n_files += 1
        seen = set()
        self._count(text_elem, inside_block=False, seen=seen)
        self.files.update(seen)

    def _count(self, elem, inside_block, seen):
        if not isinstance(elem.tag, str):
            return  # comments, processing instructions
        tag = elem.tag.split("}")[-1]
        text = direct_text(elem)
        seen.add(tag)
        self.count[tag] += 1
        if text:
            self.with_text[tag] += 1
        if inside_block:
            self.inline[tag] += 1
        for char in text:
            if char.isalpha():
                self.letters[tag] += 1
                if is_greek_letter(char):
                    self.greek_letters[tag] += 1
        for child in elem:
            self._count(child, inside_block or tag in TEXT_BLOCKS, seen)

    def ranked(self):
        """Tags that most often contain text first (ties by count, then name)."""
        return sorted(self.count, key=lambda t: (-self.with_text[t], -self.count[t], t))

    def write_csv(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["tag", "count", "with_text", "files",
                        "greek_script_share", "inline_share"])
            for tag in self.ranked():
                w.writerow([tag, self.count[tag], self.with_text[tag], self.files[tag],
                            share(self.greek_letters[tag], self.letters[tag]),
                            share(self.inline[tag], self.count[tag])])


def share(part, whole):
    return f"{part / whole:.2f}" if whole else ""


def percent(part, whole):
    return f"{part / whole:.0%}" if whole else "-"


def print_top(name, c, n=15):
    print(f"\nTop {n} tags by occurrences with text ({name}, {c.n_files} files):")
    print(f"  {'tag':<12}{'with text / count':>26}{'files':>8}{'Greek script':>14}{'inline':>8}")
    for tag in c.ranked()[:n]:
        wt, total = c.with_text[tag], c.count[tag]
        print(f"  {tag:<12}{f'{wt:,} / {total:,} ({percent(wt, total)})':>26}"
              f"{c.files[tag]:>8}{percent(c.greek_letters[tag], c.letters[tag]):>14}"
              f"{percent(c.inline[tag], total):>8}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--perseus", default=str(ROOT / "data" / "perseus"),
                    help="dataset folder built by build_dataset.py (default: data/perseus)")
    ap.add_argument("--out", default=str(ROOT / "data" / "stats"),
                    help="folder for the CSVs (default: data/stats)")
    args = ap.parse_args()

    perseus = Path(args.perseus).resolve()
    out = Path(args.out).resolve()

    with open(perseus / "pairs.csv", newline="", encoding="utf-8") as f:
        pairs = list(csv.DictReader(f))
    greek_files = sorted({r["greek_path"] for r in pairs})
    english_files = sorted({r["english_path"] for r in pairs})
    print(f"{len(pairs)} pairs: {len(greek_files)} Greek files, "
          f"{len(english_files)} English files")

    greek, all_ = TagCounts(), TagCounts()
    invalid = []
    for lang, files in (("grc", greek_files), ("eng", english_files)):
        for rel in files:
            path = perseus / rel
            try:
                root = ET.parse(path).getroot()
            except (ET.ParseError, OSError) as e:
                invalid.append((rel, e))
                continue
            text_elem = root.find("{*}text")
            if text_elem is None:
                continue
            all_.add_file(text_elem)
            if lang == "grc":
                greek.add_file(text_elem)

    for rel, e in invalid:
        print(f"Skipped (could not parse): {rel}  [{e}]")

    greek_csv = out / "perseus_tag_frequencies_greek.csv"
    all_csv = out / "perseus_tag_frequencies_all.csv"
    greek.write_csv(greek_csv)
    all_.write_csv(all_csv)

    print_top("Greek only", greek)
    print_top("Greek + English", all_)
    print(f"\nSaved:\n  {greek_csv.relative_to(ROOT).as_posix()}"
          f"\n  {all_csv.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
