"""Strip the tags of a block for hybrid translation.

A block (<p>, <l>, <head>, ...) becomes one plain string, and every child node
becomes an *anchor* that records where it was in that string:

- wrap:  an element whose text is translated (<q>, <hi>, <corr>, containers,
         unknown tags). Its text stays in the plain string; its own children
         are anchors too.
- fixed: an element whose content is kept or transliterated (<name>, <num>, ...)
         while the model still sees its words (`mt_input: source`). After
         translation the English the model produced for those words is
         replaced by the element with its fixed content.
- point: something placed at one position: empty markers (<pb/>, <milestone/>),
         kept subtrees (<note>), comments, elements with `mt_input: remove`
         (<bibl>) and elements without letters. Its text is not in the plain
         string and it is moved unchanged.

Nothing here changes the tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tei_translate.pipeline.policy import Policy
from tei_translate.pipeline.spans import has_letters, is_element

WRAP, FIXED, POINT = "wrap", "fixed", "point"


@dataclass(eq=False)
class Anchor:
    node: object            # the element (or comment / processing instruction)
    kind: str               # wrap | fixed | point
    start: int              # range in the block's plain text; start == end for points
    end: int
    params: dict
    index: int              # source order within the block
    parent: "Anchor | None" = None
    children: list = field(default_factory=list)   # wraps only

    def core(self, text: str) -> tuple[int, int]:
        """The range without leading and trailing whitespace."""
        piece = text[self.start:self.end]
        s = self.start + len(piece) - len(piece.lstrip())
        return s, max(s, self.start + len(piece.rstrip()))


@dataclass
class Detagged:
    block: object
    text: str
    anchors: list           # top-level anchors (children of the block)
    all: list               # every anchor, in source order


def mt_text(elem, policy: Policy) -> str:
    """The text of `elem` the model would see: kept subtrees (notes) and comments left out."""
    out = [elem.text or ""]
    for child in elem:
        if is_element(child) and policy.classify(child).treatment != "keep-subtree":
            out.append(mt_text(child, policy))
        out.append(child.tail or "")
    return "".join(out)


def has_block_descendant(elem, policy: Policy) -> bool:
    return any(is_element(d) and d is not elem and policy.classify(d).role == "block" for d in elem.iter())


def _kind(node, policy: Policy) -> tuple[str, dict]:
    if not is_element(node):
        return POINT, {}
    rule = policy.classify(node)
    params = dict(rule.params)
    if rule.treatment == "keep-subtree" or rule.role == "empty":
        return POINT, params
    if not has_letters(mt_text(node, policy)):
        return POINT, params
    if rule.treatment in ("keep", "transliterate"):
        if params.get("mt_input", "source") == "remove":
            return POINT, params
        return FIXED, params
    return WRAP, params     # translate: inline tags, containers inside the block, unknown tags


def detag(block, policy: Policy) -> Detagged:
    parts: list[str] = []
    pos = 0
    every: list[Anchor] = []

    def add(s):
        nonlocal pos
        if s:
            parts.append(s)
            pos += len(s)

    def content(elem, parent, out):
        add(elem.text)
        for child in elem:
            kind, params = _kind(child, policy)
            a = Anchor(child, kind, pos, pos, params, len(every), parent)
            every.append(a)
            out.append(a)
            if kind == WRAP:
                content(child, a, a.children)
            elif kind == FIXED:
                add(mt_text(child, policy))
            a.end = pos
            add(child.tail)

    top: list[Anchor] = []
    content(block, None, top)
    return Detagged(block, "".join(parts), top, every)
