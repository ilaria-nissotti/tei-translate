"""Checks run on every output: compares the translated tree with the source tree.

Elements outside text blocks (blocks, containers, markers between blocks) must
be identical and in the same order. Inside a block, hybrid placement may change
the order of inline elements (English word order differs), so there the check
is: the same elements under the same parents. Numbered sequences (@n per tag
and @unit, e.g. milestones) must keep their order everywhere. xml:lang values
that were changed from src to tgt are allowed.
"""

from __future__ import annotations

import copy
from collections import Counter, defaultdict

from lxml import etree

from tei_translate.pipeline.policy import Policy, local_name

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _texts(root):
    return root.xpath("//*[local-name()='text'][not(ancestor::*[local-name()='text'])]")


def _key(elem, src, tgt):
    attrs = dict(elem.attrib)
    if attrs.get(XML_LANG) == tgt:
        attrs[XML_LANG] = src  # an updated language counts as unchanged
    return elem.tag, tuple(sorted(attrs.items()))


def _check(ok, detail=""):
    return {"ok": bool(ok), "detail": detail}


def _walk(texts, policy: Policy):
    """[(element, inside a block?)] in document order, plus the outermost blocks' element lists."""
    entries, blocks = [], []

    def visit(elem, group):
        entries.append((elem, group is not None))
        if group is not None:
            group.append(elem)
            child_group = group
        else:
            child_group = [] if policy.classify(elem).role == "block" else None
            if child_group is not None:
                blocks.append(child_group)
        for child in elem:
            if isinstance(child.tag, str):
                visit(child, child_group)

    for t in texts:
        visit(t, None)
    return entries, blocks


def _structure(entries, blocks, src, tgt):
    """Ordered keys outside blocks; per block a multiset of (key, parent key) of the elements inside."""
    ordered = [_key(e, src, tgt) for e, inside in entries if not inside]
    inner = [Counter((_key(e, src, tgt), _key(e.getparent(), src, tgt)) for e in group) for group in blocks]
    return ordered, inner


def _sequences(entries, attr, policy: Policy):
    """Values of `attr`: in order per (tag, @unit) for elements outside blocks and empty
    markers; as a multiset for other elements inside blocks (their order may change)."""
    ordered, loose = defaultdict(list), Counter()
    for e, inside in entries:
        value = e.get(attr)
        if value is None:
            continue
        if inside and policy.classify(e).role != "empty":
            loose[(e.tag, value)] += 1
        else:
            ordered[(e.tag, e.get("unit"))].append(value)
    return dict(ordered), loose


def validate(source_tree, output_tree, policy: Policy, src: str, tgt: str) -> dict:
    checks = {}

    # 1. Well-formed: serialize and parse again.
    try:
        data = etree.tostring(output_tree, encoding="UTF-8", xml_declaration=True)
        etree.fromstring(data)
        checks["well-formed"] = _check(True)
    except etree.XMLSyntaxError as e:
        checks["well-formed"] = _check(False, str(e))

    src_texts, out_texts = _texts(source_tree.getroot()), _texts(output_tree.getroot())
    src_entries, src_blocks = _walk(src_texts, policy)
    out_entries, out_blocks = _walk(out_texts, policy)

    # 2. Same elements and attributes: in order outside blocks, same parents inside blocks.
    src_ord, src_inner = _structure(src_entries, src_blocks, src, tgt)
    out_ord, out_inner = _structure(out_entries, out_blocks, src, tgt)
    if src_ord != out_ord:
        first = next((i for i, (a, b) in enumerate(zip(src_ord, out_ord)) if a != b), min(len(src_ord), len(out_ord)))
        checks["same structure"] = _check(False, f"{len(src_ord)} vs {len(out_ord)} elements outside blocks, "
                                                 f"first difference at element {first}")
    elif src_inner != out_inner:
        first = next(i for i, (a, b) in enumerate(zip(src_inner, out_inner)) if a != b)
        checks["same structure"] = _check(False, f"block {first}: different elements or parents inside the block")
    else:
        checks["same structure"] = _check(True, f"{len(src_entries)} elements")

    # 3. Citation attributes preserved (numbered sequences in order).
    for attr, label in (("n", "@n"), (XML_ID, "@xml:id")):
        a, b = _sequences(src_entries, attr, policy), _sequences(out_entries, attr, policy)
        count = sum(len(v) for v in a[0].values()) + sum(a[1].values())
        checks[f"{label} preserved"] = _check(a == b, f"{count} values" if a == b else "values or their order differ")

    # 4. Kept elements (notes, num, bibl, foreign, ...) byte-identical (they may move inside a block).
    def kept(entries):
        return sorted(etree.tostring(e, encoding="unicode", with_tail=False) for e, _ in entries
                      if policy.classify(e).treatment in ("keep", "keep-subtree") and e.getparent() is not None)
    a, b = kept(src_entries), kept(out_entries)
    same = sum((Counter(a) & Counter(b)).values())
    checks["kept elements unchanged"] = _check(a == b, f"{same}/{len(a)} identical")

    # 5. Header unchanged apart from the added respStmt.
    def header(tree):
        found = tree.getroot().xpath("//*[local-name()='teiHeader']")
        if not found:
            return None
        h = copy.deepcopy(found[0])
        for r in h.xpath("//*[local-name()='respStmt'][*[local-name()='name']='tei-translate']"):
            r.getparent().remove(r)
        for e in h.iter():
            if isinstance(e.tag, str):
                e.tail = (e.tail or "").strip()
                e.text = (e.text or "").strip()
        return etree.tostring(h, encoding="unicode")
    checks["header unchanged"] = _check(header(source_tree) == header(output_tree))

    return checks
