"""Tests for src/tei_translate/metrics/comet_score.py.

Run from the repository root (after pip install -e .[dev]):

    pytest tests/test_comet.py -v

COMET itself is a neural model, so its scores are not worked out by hand.
Most tests check our own part instead, with a simple stand-in for the model
(fake_scorer below): that tags are removed, that every reference of a passage
is scored, that the best reference is kept, and that wrong input is refused.
These need neither PyTorch nor the model.

The tests at the end run the real COMET model. Like the real MT engines in
tests/test_engines.py, they are skipped unless TEI_TRANSLATE_RUN_MODELS=1 is
set, because the model is a 2.3 GB download (pip install -e .[comet]):

    $env:TEI_TRANSLATE_RUN_MODELS = "1"; pytest tests/test_comet.py      (PowerShell)

How pytest works is explained at the top of tests/test_metrics.py.
"""

import os

import pytest

from tei_translate.metrics.comet_score import best_per_passage, comet, comet_rows, comet_scores

# Thucydides 1.1.1 (shortened): the Greek, two Perseus translations (Crawley, Hobbes)
# and an output with tags, as the pipeline would write it.
GREEK = '<p><name type="person">Θουκυδίδης</name> Ἀθηναῖος ξυνέγραψε τὸν πόλεμον.</p>'
CRAWLEY = "<p>Thucydides, an Athenian, wrote the history of the war.</p>"
HOBBES = "<p>Thucydides, an Athenian, wrote the war of the Peloponnesians and the Athenians.</p>"
OUTPUT = '<p><name type="person">Thucydides</name> the Athenian wrote the history of the war.</p>'


def fake_scorer(rows):
    """A stand-in for the COMET model: the share of the reference's words found in the output.

    Not a real metric; it only has to give higher scores to outputs closer to
    the reference, so the tests can check which reference is kept.
    """
    scores = []
    for row in rows:
        ref_words = set(row["ref"].split())
        scores.append(len(ref_words & set(row["mt"].split())) / len(ref_words))
    return scores


# ---------------------------------------------------------------------------
# Our part, with the stand-in model
# ---------------------------------------------------------------------------

def test_rows_have_tags_removed():
    """COMET gets plain text: source, output and reference without tags."""
    rows, owners = comet_rows([GREEK], [CRAWLEY], [OUTPUT])
    assert rows == [{
        "src": "Θουκυδίδης Ἀθηναῖος ξυνέγραψε τὸν πόλεμον.",
        "mt": "Thucydides the Athenian wrote the history of the war.",
        "ref": "Thucydides, an Athenian, wrote the history of the war.",
    }]
    assert owners == [0]


def test_one_row_per_reference():
    """A passage with two references becomes two rows, both belonging to that passage."""
    rows, owners = comet_rows([GREEK, GREEK], [[CRAWLEY, HOBBES], CRAWLEY], [OUTPUT, OUTPUT])
    assert [row["ref"] for row in rows] == [
        "Thucydides, an Athenian, wrote the history of the war.",
        "Thucydides, an Athenian, wrote the war of the Peloponnesians and the Athenians.",
        "Thucydides, an Athenian, wrote the history of the war.",
    ]
    assert owners == [0, 0, 1]


def test_best_per_passage_keeps_the_highest_score():
    # Rows 0-1 belong to passage 0, row 2 to passage 1.
    assert best_per_passage([0.6, 0.8, 0.5], [0, 0, 1], 2) == [0.8, 0.5]


def test_passage_is_scored_against_its_best_reference():
    """With two references, the passage gets the score of the closer one (here Crawley)."""
    with_both = comet_scores([GREEK], [[HOBBES, CRAWLEY]], [OUTPUT], scorer=fake_scorer)
    crawley_only = comet_scores([GREEK], [CRAWLEY], [OUTPUT], scorer=fake_scorer)
    hobbes_only = comet_scores([GREEK], [HOBBES], [OUTPUT], scorer=fake_scorer)
    assert with_both == [max(crawley_only[0], hobbes_only[0])]
    assert with_both == crawley_only


def test_corpus_score_is_the_average_of_the_passages():
    sources = [GREEK, GREEK]
    references = [CRAWLEY, HOBBES]
    hypotheses = [OUTPUT, OUTPUT]
    per_passage = comet_scores(sources, references, hypotheses, scorer=fake_scorer)
    assert comet(sources, references, hypotheses, scorer=fake_scorer) == pytest.approx(sum(per_passage) / 2)


def test_broken_xml_is_still_scored():
    """As with chrF, the tags of a broken output are removed with a regular expression."""
    broken = "<p><name>Thucydides</p></name> the Athenian wrote the history of the war."
    rows, _ = comet_rows([GREEK], [CRAWLEY], [broken])
    assert rows[0]["mt"] == "Thucydides the Athenian wrote the history of the war."


def test_wrong_input_is_refused():
    with pytest.raises(ValueError):
        comet([GREEK], [CRAWLEY], [], scorer=fake_scorer)                 # 1 reference, 0 outputs
    with pytest.raises(ValueError):
        comet([], [CRAWLEY], [OUTPUT], scorer=fake_scorer)                # 0 sources, 1 output
    with pytest.raises(ValueError):
        comet([GREEK], [[]], [OUTPUT], scorer=fake_scorer)                # a passage without reference


def test_empty_test_set_gives_none():
    assert comet([], [], [], scorer=fake_scorer) is None


# ---------------------------------------------------------------------------
# The real COMET model (only with TEI_TRANSLATE_RUN_MODELS=1)
# ---------------------------------------------------------------------------

run_models = pytest.mark.skipif(os.environ.get("TEI_TRANSLATE_RUN_MODELS") != "1",
                                reason="set TEI_TRANSLATE_RUN_MODELS=1 to run the real COMET model")


@run_models
def test_real_comet_prefers_a_correct_translation():
    """A faithful translation scores higher than an unrelated sentence, and scores lie in 0-1."""
    pytest.importorskip("comet")
    good, bad = comet_scores([GREEK, GREEK], [CRAWLEY, CRAWLEY],
                             [OUTPUT, "<p>The weather is nice today.</p>"])
    assert 0 <= bad < good <= 1


@run_models
def test_real_comet_ignores_tags():
    """The same text with and without tags gets the same score."""
    pytest.importorskip("comet")
    with_tags = comet([GREEK], [CRAWLEY], [OUTPUT])
    without_tags = comet([GREEK], [CRAWLEY], ["Thucydides the Athenian wrote the history of the war."])
    assert with_tags == pytest.approx(without_tags, abs=1e-6)
