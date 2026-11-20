"""Hybrid translation: whole sentences go to the model, tags are placed afterwards.

For every block that can be handled this way (treatment translate, no blocks
inside it):

1. detag.detag: plain text + anchors (tags) with their positions;
2. the plain text is split into sentences; all sentences of all blocks go to
   the engine in one batch;
3. sentences with a tag edge inside them are word-aligned (one batch);
4. placement.place puts every tag in the English text, placement.rebuild
   writes the block.

A block whose tags cannot be placed (`fallback: spanwise`) is left untouched
and handed back, with all other text, to the span-wise path.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from tei_translate.pipeline.detag import detag, has_block_descendant
from tei_translate.pipeline.placement import Fallback, Layout, place, rebuild
from tei_translate.pipeline.policy import Policy
from tei_translate.pipeline.sentences import split_sentences
from tei_translate.pipeline.spans import has_letters, is_element


@dataclass
class HybridReport:
    blocks: int = 0                                          # blocks placed in hybrid mode
    sentences: int = 0                                       # sentences sent to the engine
    aligned_sentences: int = 0                               # sentences sent to the aligner
    spanwise: Counter = field(default_factory=Counter)       # reason -> blocks translated span-wise
    placements: Counter = field(default_factory=Counter)     # how each tag was placed


def _block_of(span, policy: Policy):
    e = span.elem if span.slot == "text" else span.elem.getparent()
    while e is not None:
        if is_element(e) and policy.classify(e).role == "block":
            return e
        e = e.getparent()
    return None


def group_spans(spans, policy: Policy, stats: HybridReport) -> tuple[dict, list]:
    """Split spans into {hybrid block: its spans} and the spans that stay span-wise."""
    groups: dict = {}
    rest = []
    for span in spans:
        block = _block_of(span, policy)
        if block is None:
            rest.append(span)
        else:
            groups.setdefault(block, []).append(span)
    hybrid = {}
    for block, bspans in groups.items():
        if policy.classify(block).treatment != "translate" or not any(s.treatment == "translate" for s in bspans):
            rest += bspans
        elif has_block_descendant(block, policy):
            stats.spanwise["contains-blocks"] += 1
            rest += bspans
        else:
            hybrid[block] = bspans
    return hybrid, rest


def run_hybrid(spans, policy: Policy, engine, aligner, src: str, tgt: str, stats: HybridReport) -> list:
    """Translate and place the hybrid blocks in place; return the spans left for the span-wise path."""
    hybrid, rest = group_spans(spans, policy, stats)

    jobs = []   # (block, its spans, detagged, sentences)
    for block, bspans in hybrid.items():
        det = detag(block, policy)
        sents = split_sentences(det.text)
        if sents:
            jobs.append((block, bspans, det, sents))
        else:
            rest += bspans

    # 1. One engine batch with every sentence (sentences without letters are copied).
    segments = [" ".join(det.text[s:e].split()) for _, _, det, sents in jobs for s, e in sents]
    to_mt = [n for n, seg in enumerate(segments) if has_letters(seg)]
    outputs = engine.translate([segments[n] for n in to_mt], src, tgt) if to_mt else []
    if len(outputs) != len(to_mt):
        raise RuntimeError(f"engine {engine.name} returned {len(outputs)} segments for {len(to_mt)}")
    translated = list(segments)
    for n, out in zip(to_mt, outputs):
        translated[n] = out
    stats.sentences += len(to_mt)

    layouts, n = [], 0
    for _, _, det, sents in jobs:
        layouts.append(Layout(det, sents, translated[n:n + len(sents)]))
        n += len(sents)

    # 2. One aligner batch with every sentence that has a tag edge inside it.
    where, pairs = [], []
    for layout in layouts:
        for k in sorted(layout.needs_alignment()):
            where.append((layout, k))
            pairs.append(layout.pair(k))
    links = aligner.align(pairs) if pairs and aligner is not None else [set() for _ in pairs]
    for (layout, k), lk in zip(where, links):
        layout.set_links(k, lk)
    stats.aligned_sentences += len(pairs)

    # 3. Place and rebuild; blocks that cannot be placed go span-wise.
    for (block, bspans, _, _), layout in zip(jobs, layouts):
        try:
            placed, counts = place(layout)
        except Fallback as f:
            stats.spanwise[f.reason] += 1
            rest += bspans
            continue
        rebuild(block, layout.english, placed)
        stats.blocks += 1
        stats.placements.update(counts)
        # Content of fixed elements (names) still needs its transliteration.
        rest += [s for s in bspans if s.treatment != "translate"]
    return rest
