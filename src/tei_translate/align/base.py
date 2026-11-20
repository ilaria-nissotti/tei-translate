"""Word aligner interface and the word tokenizer shared by the aligners and the placement."""

from __future__ import annotations

import re
from typing import Protocol

# A word: letters/digits with their combining accents, or one punctuation character.
# U+02BC (Greek elision ʼ) counts as a letter, so ἀλλʼ is one word.
WORD = re.compile(r"[\ẁ-ͯ]+|[^\w\s]")


def word_spans(text: str, offset: int = 0) -> list[tuple[int, int]]:
    """Character ranges of the words in `text`, shifted by `offset`."""
    return [(m.start() + offset, m.end() + offset) for m in WORD.finditer(text)]


Links = set[tuple[int, int]]   # (source word index, target word index)


class Aligner(Protocol):
    name: str

    def align(self, pairs: list[tuple[list[str], list[str]]]) -> list[Links]:
        """For each (source words, target words) pair, the aligned word index pairs."""
        ...
