"""Sentence splitting shared by the engines and the hybrid placement.

The engines split long segments into sentences before translating them
(engines/hf.py); the hybrid pipeline sends one sentence per segment, so both
use the same sentence ends.
"""

from __future__ import annotations

import re

# Sentence ends: . ! ? and the Greek question mark (";" U+003B or U+037E).
SENTENCE_END = re.compile(r"(?<=[.!?;;])\s+")


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Character ranges (start, end) of the sentences in `text`.

    Whitespace around and between sentences is not part of any range. Text
    with no sentence end is one sentence; whitespace-only text gives [].
    """
    ranges = []
    start = 0
    for m in SENTENCE_END.finditer(text):
        ranges.append((start, m.start()))
        start = m.end()
    ranges.append((start, len(text)))
    out = []
    for s, e in ranges:
        piece = text[s:e]
        core = piece.strip()
        if core:
            s += len(piece) - len(piece.lstrip())
            out.append((s, s + len(core)))
    return out
