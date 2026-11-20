import os

import numpy as np
import pytest

from tei_translate.align import get_aligner, word_spans
from tei_translate.align.embed import argmax_links, itermax_links
from tei_translate.pipeline.sentences import split_sentences


def words(text):
    return [text[s:e] for s, e in word_spans(text)]


def test_word_spans_keep_greek_words_whole():
    assert words("ἀλλʼ ἐγὼ μέμνημαι· τί φής;") == ["ἀλλʼ", "ἐγὼ", "μέμνημαι", "·", "τί", "φής", ";"]


def test_split_sentences_ranges():
    text = "  τί φής; οὐδὲν λέγεις.\n ναί  "
    assert [text[s:e] for s, e in split_sentences(text)] == ["τί φής;", "οὐδὲν λέγεις.", "ναί"]
    assert split_sentences(" \n ") == []


def test_registry():
    assert get_aligner("none").align([(["a"], ["b"])]) == [set()]
    assert get_aligner("monotone").align([(["a", "b", "c"], ["x", "y", "z"])]) == [{(0, 0), (1, 1), (2, 2)}]
    assert get_aligner("embed:some/model").model_id == "some/model"
    with pytest.raises(ValueError):
        get_aligner("nope")


def test_argmax_and_itermax():
    sim = np.array([[0.9, 0.1, 0.0],
                    [0.8, 0.3, 0.1],
                    [0.0, 0.2, 0.7]])
    # Row 1's best match (column 0) is taken by row 0: argmax leaves it out ...
    assert set(zip(*argmax_links(sim).nonzero())) == {(0, 0), (2, 2)}
    # ... itermax links it in a second round, here to the same column (many-to-one is allowed).
    assert set(zip(*itermax_links(sim).nonzero())) == {(0, 0), (1, 0), (2, 2)}


@pytest.mark.skipif(os.environ.get("TEI_TRANSLATE_RUN_MODELS") != "1",
                    reason="set TEI_TRANSLATE_RUN_MODELS=1 to run real models")
def test_ugarit_links_names_and_verbs():
    src, tgt = words("ὁ Περικλῆς εἶπε τοῖς Ἀθηναίοις ."), words("Pericles said to the Athenians .")
    links = get_aligner("ugarit").align([(src, tgt)])[0]
    pairs = {(src[i], tgt[j]) for i, j in links}
    assert {("Περικλῆς", "Pericles"), ("εἶπε", "said"), ("Ἀθηναίοις", "Athenians")} <= pairs
