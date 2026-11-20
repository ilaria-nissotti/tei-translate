"""Place the tags of a detagged block in its translation, then rebuild the block.

The block's plain text was split into sentences and each sentence translated
on its own, so sentence boundaries correspond exactly. Inside a sentence the
word alignment says which English words came from which Greek words.

Per anchor (see detag.py), driven by the rule's params in config/policy.yaml:

- wrap / fixed: if the element covers whole sentences it covers the same
  English sentences. Otherwise it gets the smallest English span covering
  every English word aligned to its Greek words. A fixed element's span is
  replaced by the element with its own (kept or transliterated) content.
- point: between two sentences it stays between them. Inside a sentence,
  `placement: boundary` puts it at the nearer edge of the English sentence;
  `placement: align` attaches it after the English of the previous Greek word
  (`anchor: left`) or before that of the next one (`anchor: right`).

When an anchor cannot be placed, its `fallback` decides: `boundary` (points),
`sentence` (wraps: cover the whole English sentence) or `spanwise` (default):
`Fallback` is raised and the caller translates the whole block span-wise.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from tei_translate.align.base import word_spans
from tei_translate.pipeline.detag import POINT, WRAP, Anchor, Detagged
from tei_translate.pipeline.policy import local_name
from tei_translate.pipeline.spans import is_element


class Fallback(Exception):
    """The block cannot be placed: translate it span-wise."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(eq=False)
class Placed:
    anchor: Anchor
    start: int              # range in the English text; start == end for points
    end: int
    pad_after: bool = False  # add a space after a point (it had spaces on both sides)
    children: list = field(default_factory=list)


def _name(anchor: Anchor) -> str:
    return local_name(anchor.node) if is_element(anchor.node) else "comment"


class Layout:
    """A block's plain text, its sentences, their translations and the word links."""

    def __init__(self, det: Detagged, sentences: list[tuple[int, int]], translations: list[str]):
        self.det = det
        self.text = text = det.text
        self.sents = sentences
        lead = text[:len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        parts, pos, self.eoff = [lead], len(lead), []
        for k, t in enumerate(translations):
            if k:
                parts.append(" ")
                pos += 1
            self.eoff.append((pos, pos + len(t)))
            parts.append(t)
            pos += len(t)
        parts.append(trail)
        self.english = "".join(parts)
        self.swords = [word_spans(text[s:e], s) for s, e in sentences]
        self.ewords = [word_spans(self.english[s:e], s) for s, e in self.eoff]
        self.links: list[dict] = [{} for _ in sentences]   # per sentence: source word -> target words

    # -- sentences --------------------------------------------------------------

    def containing(self, pos: int) -> int | None:
        for k, (s, e) in enumerate(self.sents):
            if s <= pos < e:
                return k
        return None

    def locate(self, pos: int) -> tuple[str, int]:
        """("in", k) strictly inside sentence k, else ("gap", g): before sentence g (g == n: after the last)."""
        for k, (s, e) in enumerate(self.sents):
            if s < pos < e:
                return "in", k
        return "gap", sum(1 for _, e in self.sents if e <= pos)

    def gap_position(self, g: int, glued_right: bool = False) -> int:
        """End of the sentence before gap g; start of the next one if the point was glued to it."""
        if g == 0 or (glued_right and g < len(self.eoff)):
            return self.eoff[g][0]
        return self.eoff[g - 1][1]

    def boundary(self, k: int, pos: int) -> int:
        s, e = self.sents[k]
        return self.eoff[k][0] if (pos - s) < (e - s) / 2 else self.eoff[k][1]

    # -- alignment --------------------------------------------------------------

    def needs_alignment(self) -> set[int]:
        """Sentences with a tag edge or an aligned point strictly inside them."""
        need = set()
        for a in self.det.all:
            if a.kind == POINT:
                if a.params.get("placement", "boundary") == "align":
                    where, k = self.locate(a.start)
                    if where == "in":
                        need.add(k)
                continue
            s, e = a.core(self.text)
            k1, k2 = self.containing(s), self.containing(e - 1)
            if k1 is None or k2 is None:
                continue
            if s != self.sents[k1][0]:
                need.add(k1)
            if e != self.sents[k2][1]:
                need.add(k2)
        return need

    def pair(self, k: int) -> tuple[list[str], list[str]]:
        return ([self.text[s:e] for s, e in self.swords[k]],
                [self.english[s:e] for s, e in self.ewords[k]])

    def set_links(self, k: int, links) -> None:
        m = len(self.ewords[k])
        d: dict[int, list[int]] = {}
        for i, j in links:
            if 0 <= j < m:
                d.setdefault(i, []).append(j)
        self.links[k] = d

    def cover(self, k: int, s: int, e: int) -> tuple[int, list[int]]:
        """(number of source words in [s, e), sorted target words aligned to them) in sentence k."""
        src = [i for i, (ws, we) in enumerate(self.swords[k]) if ws < e and we > s]
        tgt = sorted({j for i in src for j in self.links[k].get(i, ())})
        return len(src), tgt

    def anchor_word(self, k: int, pos: int, side: str) -> int | None:
        words, links, ewords = self.swords[k], self.links[k], self.ewords[k]
        if side == "right":
            for i, (ws, _) in enumerate(words):
                if ws >= pos and links.get(i):
                    return ewords[min(links[i])][0]
        else:
            for i in range(len(words) - 1, -1, -1):
                if words[i][1] <= pos and links.get(i):
                    return ewords[max(links[i])][1]
        return None


# -- placement ------------------------------------------------------------------

def place(layout: Layout) -> tuple[list[Placed], Counter]:
    """Place every anchor of the block. Raises Fallback if the block must go span-wise."""
    counts: Counter = Counter()
    placed = _place_list(layout, layout.det.anchors, (0, len(layout.english)), counts)
    return placed, counts


def _place_list(layout: Layout, anchors: list[Anchor], bounds: tuple[int, int], counts: Counter) -> list[Placed]:
    placed = [_place_one(layout, a, bounds, counts) for a in anchors]
    ranges = sorted((p for p in placed if p.anchor.kind != POINT), key=lambda p: (p.start, p.end))
    for a, b in zip(ranges, ranges[1:]):
        if b.start < a.end:
            raise Fallback(f"{_name(b.anchor)}:overlap")
    points = [p for p in placed if p.anchor.kind == POINT]
    # Markers of the same kind (e.g. milestones of one unit) keep their order.
    last: dict = {}
    for p in points:
        node = p.anchor.node
        key = (node.tag, node.get("unit")) if is_element(node) else None
        if key is not None:
            if key in last and p.start < last[key]:
                p.start = p.end = last[key]
                counts["kept-in-order"] += 1
            last[key] = p.start
    # A point must not fall inside a sibling element (it would change parent).
    for p in points:
        for r in ranges:
            if r.start < p.start < r.end:
                p.start = p.end = r.start if p.start - r.start <= r.end - p.start else r.end
                counts["moved-out"] += 1
    return placed


def _place_one(layout: Layout, a: Anchor, bounds: tuple[int, int], counts: Counter) -> Placed:
    lo, hi = bounds
    if a.kind == POINT:
        p, how = _point(layout, a)
        p, pad = _spacing(layout, a, p)
        if not lo <= p <= hi:
            p = lo if abs(p - lo) <= abs(p - hi) else hi
            how = "clamped"
        counts[how] += 1
        return Placed(a, p, p, pad)

    try:
        s, e, how = _range(layout, a)
    except Fallback as f:
        s, e, how = _range_fallback(layout, a, f.reason)
    if not (lo <= s and e <= hi):
        if a.params.get("fallback") != "sentence":
            raise Fallback(f"{_name(a)}:outside-parent")
        s, e, how = max(s, lo), min(e, hi), "fallback-sentence"
        if s > e:
            raise Fallback(f"{_name(a)}:outside-parent")
    counts[how] += 1
    placed = Placed(a, s, e)
    if a.kind == WRAP:
        placed.children = _place_list(layout, a.children, (s, e), counts)
    return placed


def _point(layout: Layout, a: Anchor) -> tuple[int, str]:
    where, k = layout.locate(a.start)
    if where == "gap":
        text = layout.text
        glued_right = a.start < len(text) and not text[a.start].isspace()
        return layout.gap_position(k, glued_right), "between-sentences"
    if a.params.get("placement", "boundary") != "align":
        return layout.boundary(k, a.start), "boundary"
    p = layout.anchor_word(k, a.start, a.params.get("anchor", "left"))
    if p is not None:
        return p, "aligned"
    if a.params.get("fallback", "spanwise") == "boundary":
        return layout.boundary(k, a.start), "fallback-boundary"
    raise Fallback(f"{_name(a)}:unaligned")


def _spacing(layout: Layout, a: Anchor, p: int) -> tuple[int, bool]:
    """Keep a point that stood between two spaces between two words, not glued to one."""
    text, eng = layout.text, layout.english
    gap_before = a.start == 0 or text[a.start - 1].isspace()
    gap_after = a.start >= len(text) or text[a.start].isspace()
    if not (gap_before and gap_after):
        return p, False
    if 0 < p < len(eng) and eng[p].isspace() and not eng[p - 1].isspace():
        p += 1
    pad = 0 < p < len(eng) and eng[p - 1].isspace() and not eng[p].isspace()
    return p, pad


def _range(layout: Layout, a: Anchor) -> tuple[int, int, str]:
    s, e = a.core(layout.text)
    k1, k2 = layout.containing(s), layout.containing(e - 1)
    if k1 is None or k2 is None:
        raise Fallback("no-sentence")
    if s == layout.sents[k1][0] and e == layout.sents[k2][1]:
        return layout.eoff[k1][0], layout.eoff[k2][1], "whole-sentence"
    ew = layout.ewords
    if k1 == k2:
        n_src, tgt = layout.cover(k1, s, e)
        if not tgt:
            raise Fallback("unaligned")
        if tgt[-1] - tgt[0] + 1 > 2 * n_src + 3:
            raise Fallback("too-wide")
        return ew[k1][tgt[0]][0], ew[k1][tgt[-1]][1], "aligned"
    if s == layout.sents[k1][0]:
        start = layout.eoff[k1][0]
    else:
        _, tgt = layout.cover(k1, s, e)
        if not tgt:
            raise Fallback("unaligned")
        start = ew[k1][tgt[0]][0]
    if e == layout.sents[k2][1]:
        end = layout.eoff[k2][1]
    else:
        _, tgt = layout.cover(k2, s, e)
        if not tgt:
            raise Fallback("unaligned")
        end = ew[k2][tgt[-1]][1]
    return start, end, "aligned"


def _range_fallback(layout: Layout, a: Anchor, reason: str) -> tuple[int, int, str]:
    if a.kind == WRAP and a.params.get("fallback") == "sentence":
        s, e = a.core(layout.text)
        k1, k2 = layout.containing(s), layout.containing(e - 1)
        if k1 is not None and k2 is not None:
            return layout.eoff[k1][0], layout.eoff[k2][1], "fallback-sentence"
    raise Fallback(f"{_name(a)}:{reason}")


# -- rebuild --------------------------------------------------------------------

def rebuild(block, english: str, placed: list[Placed]) -> None:
    """Replace the block's content with the English text and the placed nodes."""
    _fill(block, english, 0, len(english), placed)


def _fill(elem, eng: str, start: int, end: int, items: list[Placed]) -> None:
    items = sorted(items, key=lambda p: (p.start, p.end, p.anchor.index))
    for child in list(elem):
        elem.remove(child)
    elem.text = (eng[start:items[0].start] if items else eng[start:end]) or None
    for n, it in enumerate(items):
        node = it.anchor.node
        elem.append(node)
        if it.anchor.kind == WRAP:
            _fill(node, eng, it.start, it.end, it.children)
        nxt = items[n + 1].start if n + 1 < len(items) else end
        tail = eng[it.end:nxt]
        if it.pad_after and not tail[:1].isspace():
            tail = " " + tail
        node.tail = tail or None
