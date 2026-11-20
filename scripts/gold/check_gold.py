"""Validate a gold TEI XML translation against its Greek source.

Usage:
    python scripts/gold/check_gold.py GREEK.xml GOLD.xml
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

from tei_translate.pipeline.policy import DEFAULT_POLICY, Policy, local_name
from tei_translate.pipeline.validate import _key, _texts, _walk, validate

GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]+")


def _block_label(elem, index: int) -> str:
    """Human-readable citation path for a block element, e.g. 'block 3 (1.2 <p>)'."""
    parts = []
    cur = elem.getparent()
    while cur is not None:
        if isinstance(cur.tag, str) and local_name(cur) == "div" and cur.get("type") == "textpart":
            n = cur.get("n")
            if n:
                parts.append(n)
        cur = cur.getparent()
    parts.reverse()
    ref = ".".join(parts) if parts else "?"
    return f"block {index} ({ref} <{local_name(elem)}>)"


def _format_key(key) -> str:
    tag, attrs = key
    name = etree.QName(tag).localname
    if not attrs:
        return f"<{name}>"
    attr_str = " ".join(f"{etree.QName(k).localname}={v!r}" for k, v in attrs)
    return f"<{name} {attr_str}>"


def _find_untranslated_greek(block, policy: Policy) -> list[str]:
    """Return snippets of Greek text inside `block` that are outside keep / keep-subtree elements."""
    hits: list[str] = []

    def visit(elem, protected: bool):
        rule = policy.classify(elem)
        if rule.treatment == "keep-subtree":
            return
        in_keep = protected or rule.treatment == "keep"
        if not in_keep and elem.text:
            m = GREEK_RE.search(elem.text)
            if m:
                start = max(0, m.start() - 15)
                end = min(len(elem.text), m.end() + 15)
                hits.append(elem.text[start:end].strip())
        for child in elem:
            if isinstance(child.tag, str):
                visit(child, in_keep)
            if not protected and child.tail:
                m = GREEK_RE.search(child.tail)
                if m:
                    start = max(0, m.start() - 15)
                    end = min(len(child.tail), m.end() + 15)
                    hits.append(child.tail[start:end].strip())

    visit(block, False)
    return hits


def _outer_blocks(tree, policy: Policy):
    blocks = []

    def visit(elem):
        if policy.classify(elem).role == "block":
            blocks.append(elem)
            return
        for child in elem:
            if isinstance(child.tag, str):
                visit(child)

    for t in _texts(tree.getroot()):
        visit(t)
    return blocks


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a gold TEI translation against its Greek source.")
    parser.add_argument("greek", type=Path, help="Path to the Greek source TEI XML file.")
    parser.add_argument("gold", type=Path, help="Path to the gold English TEI XML file.")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY, help="Path to policy.yaml.")
    parser.add_argument("--src", default="grc", help="Source language code (default: grc).")
    parser.add_argument("--tgt", default="en", help="Target language code (default: en).")
    args = parser.parse_args()

    policy = Policy.load(args.policy)
    source_tree = etree.parse(str(args.greek))
    gold_tree = etree.parse(str(args.gold))

    checks = validate(source_tree, gold_tree, policy, args.src, args.tgt)
    all_ok = True
    for name, result in checks.items():
        status = "PASS" if result["ok"] else "FAIL"
        detail = f" ({result['detail']})" if result.get("detail") else ""
        print(f"[{status}] {name}{detail}")
        if not result["ok"]:
            all_ok = False

    # Per-block element diff (missing / extra / changed attributes)
    _, src_groups = _walk(_texts(source_tree.getroot()), policy)
    _, out_groups = _walk(_texts(gold_tree.getroot()), policy)
    src_blocks = _outer_blocks(source_tree, policy)
    out_blocks = _outer_blocks(gold_tree, policy)

    if len(src_blocks) != len(out_blocks):
        print(f"\n[WARN] Block count mismatch: source has {len(src_blocks)}, gold has {len(out_blocks)}")
    else:
        diff_count = 0
        for i, (sb, sg, ob, og) in enumerate(zip(src_blocks, src_groups, out_blocks, out_groups)):
            sc = Counter((_key(e, args.src, args.tgt), _key(e.getparent(), args.src, args.tgt)) for e in sg)
            oc = Counter((_key(e, args.src, args.tgt), _key(e.getparent(), args.src, args.tgt)) for e in og)
            if sc != oc:
                diff_count += 1
                print(f"\n[DIFF] {_block_label(sb, i)}:")
                for (ek, pk), cnt in (sc - oc).items():
                    print(f"  missing x{cnt}: {_format_key(ek)} under {_format_key(pk)}")
                for (ek, pk), cnt in (oc - sc).items():
                    print(f"  extra   x{cnt}: {_format_key(ek)} under {_format_key(pk)}")
        if diff_count:
            all_ok = False

    # Check for leftover Greek outside kept elements
    greek_blocks = 0
    for i, ob in enumerate(out_blocks):
        hits = _find_untranslated_greek(ob, policy)
        if hits:
            greek_blocks += 1
            print(f"\n[GREEK] {_block_label(ob, i)}: {len(hits)} snippet(s) with Greek letters:")
            for h in hits[:5]:
                print(f"  ...{h}...")
    if greek_blocks:
        all_ok = False
        print(f"\n[FAIL] untranslated Greek found in {greek_blocks} block(s)")
    else:
        print("[PASS] no untranslated Greek outside kept elements")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
