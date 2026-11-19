"""The MT engine interface. The pipeline only ever talks to this."""

from __future__ import annotations

from typing import Protocol


class MTEngine(Protocol):
    name: str

    def translate(self, segments: list[str], src: str, tgt: str) -> list[str]:
        """Translate a batch of plain-text segments (no XML). Same length and order out."""
        ...
