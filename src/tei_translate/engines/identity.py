"""Test engines that need no model."""

from __future__ import annotations


class IdentityEngine:
    """Returns its input unchanged: for structure round-trip tests."""

    name = "identity"

    def translate(self, segments: list[str], src: str, tgt: str) -> list[str]:
        return list(segments)


class TagEngine:
    """Wraps each segment as [EN:...], so you can see exactly what was sent to MT."""

    name = "tag"

    def translate(self, segments: list[str], src: str, tgt: str) -> list[str]:
        label = tgt.upper()
        return [f"[{label}:{s}]" for s in segments]
