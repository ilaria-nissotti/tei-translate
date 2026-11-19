"""Transliteration of names into Latin script, one scheme per source language.

Only a simple Greek scheme exists so far (Περικλῆς -> Perikles). Standard
English forms (Pericles) need a name list and come later.
"""

from __future__ import annotations

import re
import unicodedata

ROUGH = "̔"  # combining reversed comma above (rough breathing)

_SINGLE = {
    "α": "a", "β": "b", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "e",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y",
    "φ": "ph", "χ": "ch", "ψ": "ps", "ω": "o", "ϝ": "w", "ϲ": "s",
}
# Checked before single letters (lower case, no diacritics).
_PAIRS = {
    "γγ": "ng", "γκ": "nk", "γξ": "nx", "γχ": "nch",
    "αυ": "au", "ευ": "eu", "ηυ": "eu", "ου": "ou", "υι": "ui",
}
_VOWELS = set("αεηιουω")


def _word_grc_simple(word: str) -> str:
    decomposed = unicodedata.normalize("NFD", word)
    # Rough breathing within the first vowel group -> leading h (rh for initial rho).
    rough_at = None
    letters = []  # base letters, with flag for rough breathing
    for ch in decomposed:
        if unicodedata.combining(ch):
            if ch == ROUGH and letters:
                rough_at = len(letters) - 1
            continue
        letters.append(ch)
    base = "".join(letters)
    lower = base.lower()

    out = []
    i = 0
    while i < len(base):
        pair = lower[i:i + 2]
        if pair in _PAIRS:
            chunk, step = _PAIRS[pair], 2
        elif lower[i] in _SINGLE:
            chunk, step = _SINGLE[lower[i]], 1
        else:
            chunk, step = base[i], 1  # not Greek: copy
        if base[i].isupper() and base[i].lower() != base[i]:
            chunk = chunk[:1].upper() + chunk[1:]
        out.append(chunk)
        i += step
    result = "".join(out)

    if rough_at is not None and rough_at <= 1:
        first = lower[:1]
        if first == "ρ":
            result = result[:1] + "h" + result[1:]
        elif first in _VOWELS:
            capital = result[:1].isupper()
            result = ("H" if capital else "h") + (result[:1].lower() if capital else result[:1]) + result[1:]
    return result


def grc_simple(text: str) -> str:
    return re.sub(r"\w+", lambda m: _word_grc_simple(m.group(0)), text)


SCHEMES = {("grc", "simple"): grc_simple}


def get_transliterator(src: str, scheme: str = "simple"):
    try:
        return SCHEMES[(src, scheme)]
    except KeyError:
        raise ValueError(f"no transliteration scheme {scheme!r} for language {src!r}") from None
