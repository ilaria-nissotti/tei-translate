"""Aligners that need no model, for tests and as a no-aligner setting."""

from __future__ import annotations

from tei_translate.align.base import Links


class NoAligner:
    """Never links anything: every tag that needs alignment takes its fallback."""

    name = "none"

    def align(self, pairs: list[tuple[list[str], list[str]]]) -> list[Links]:
        return [set() for _ in pairs]


class MonotoneAligner:
    """Links words along the diagonal (word i of n to word i*m/n of m).

    Exact when source and target have the same words in the same order (the
    identity engine); a rough guess otherwise.
    """

    name = "monotone"

    def align(self, pairs: list[tuple[list[str], list[str]]]) -> list[Links]:
        out = []
        for src, tgt in pairs:
            n, m = len(src), len(tgt)
            out.append({(i, min(m - 1, (2 * i + 1) * m // (2 * n))) for i in range(n)} if n and m else set())
        return out
