"""Checks run on every output: compares the translated tree with the source tree.

Span-wise translation never moves an element, so the structure must be
identical in order (stricter than metrics.scores.same_structure, which allows
reordering). xml:lang values that were changed from src to tgt are allowed.
"""

from __future__ import annotations

import copy

from lxml import etree

from tei_translate.pipeline.policy import Policy, local_name

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _texts(root):
    return root.xpath("//*[local-name()='text'][not(ancestor::*[local-name()='text'])]")


def _elements(elem):
    """All elements in document order, comments and processing instructions excluded."""
    return [e for e in elem.iter() if isinstance(e.tag, str)]


def _key(elem, src, tgt):
    attrs = dict(elem.attrib)
    if attrs.get(XML_LANG) == tgt:
        attrs[XML_LANG] = src  # an updated language counts as unchanged
    return elem.tag, tuple(sorted(attrs.items()))


def _check(ok, detail=""):
    return {"ok": bool(ok), "detail": detail}


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
    src_elems = [e for t in src_texts for e in _elements(t)]
    out_elems = [e for t in out_texts for e in _elements(t)]

    # 2. Same elements, same attributes, same order.
    src_keys = [_key(e, src, tgt) for e in src_elems]
    out_keys = [_key(e, src, tgt) for e in out_elems]
    if src_keys == out_keys:
        checks["same structure"] = _check(True, f"{len(src_keys)} elements")
    else:
        first = next((i for i, (a, b) in enumerate(zip(src_keys, out_keys)) if a != b), min(len(src_keys), len(out_keys)))
        checks["same structure"] = _check(False, f"{len(src_keys)} vs {len(out_keys)} elements, first difference at element {first}")

    # 3. Citation attributes preserved in order.
    for attr, label in (("n", "@n"), (XML_ID, "@xml:id")):
        a = [e.get(attr) for e in src_elems if e.get(attr) is not None]
        b = [e.get(attr) for e in out_elems if e.get(attr) is not None]
        checks[f"{label} preserved"] = _check(a == b, f"{len(a)} values" if a == b else f"{len(a)} vs {len(b)} values")

    # 4. Kept elements (notes, num, bibl, foreign, ...) byte-identical.
    def kept(elems):
        return [etree.tostring(e, encoding="unicode", with_tail=False) for e in elems
                if policy.classify(e).treatment in ("keep", "keep-subtree") and e.getparent() is not None]
    a, b = kept(src_elems), kept(out_elems)
    same = sum(x == y for x, y in zip(a, b))
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
