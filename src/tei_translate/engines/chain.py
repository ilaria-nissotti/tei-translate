"""Pivot translation: run two engines one after the other through a pivot language."""

from __future__ import annotations


class ChainEngine:
    """src -> pivot with `first`, then pivot -> tgt with `second`.

    The pivot-language text of the last call is kept in `last_intermediate`
    (one string per segment), so it can be inspected or shown in a UI.
    """

    def __init__(self, first, second, pivot: str):
        self.first = first
        self.second = second
        self.pivot = pivot
        self.name = f"{first.name} -> {second.name}"   # recorded in the respStmt
        self.last_intermediate: list[str] = []

    def translate(self, segments: list[str], src: str, tgt: str) -> list[str]:
        middle = self.first.translate(segments, src, self.pivot)
        self.last_intermediate = middle
        return self.second.translate(middle, self.pivot, tgt)
