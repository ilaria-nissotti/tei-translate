"""Tests for src/tei_translate/metrics/placement_eval.py (scoring tag placement against the gold set).

Run from the repository root (after pip install -e .[dev]):

    pytest tests/test_placement_eval.py -v

The test data (tests/fixtures/placement_eval/, described in its README) has the
same layout as the real gold set: a hand-made Greek TEI file under perseus/,
its gold translation and translations.csv under gold/. Each paragraph tests
one case. The English has the same words in the same order as the Greek, so
the "monotone" test aligner links the words exactly and the right placement is
known in advance; the "none" aligner links nothing, so tags that need
alignment take their fallback. Neither needs a model. Every expected value is
worked out by hand. Positions are counted without spaces (the evaluation uses
score(..., ignore_whitespace=True, ignore_punctuation=True)).

How pytest works is explained at the top of tests/test_metrics.py.
"""

from pathlib import Path

import pytest

from tei_translate.align import get_aligner
from tei_translate.metrics.placement_eval import (
    evaluate, find_greek_file, fixed_as_wrap, group_sentences, load_index, load_policy, make_method, score_file,
    sentence_plan, with_wrap_fallback,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "placement_eval"
FILES = load_index(FIXTURES / "gold", FIXTURES / "perseus")
POLICY = load_policy()                       # fixed elements (label, speaker, term, foreign) scored as wraps (the default)
POLICY_AS_IS = load_policy(as_wrap=False)    # the pipeline's policy unchanged


def results(aligner="monotone", policy=POLICY):
    """The result of every scorable paragraph of the test file, in order."""
    return score_file(FILES[0], policy, get_aligner(aligner))


# The paragraphs of the test file, in order (index into results()).
Q_RIGHT, Q_GOLD_EARLIER, GROUPED, NOTE, WHOLE, FIXED, NO_TAGS, UNTRANSLATED, MILESTONE = range(9)


# ---------------------------------------------------------------------------
# Reading the gold set
# ---------------------------------------------------------------------------

def test_load_index_finds_the_gold_file_and_its_greek_source():
    assert len(FILES) == 1
    entry = FILES[0]
    assert entry["gold_file"] == "test.test001.perseus-grc1.en.xml"
    assert entry["greek_path"].name == "test.test001.perseus-grc1.xml"
    assert entry["status"] == "partial"


def test_greek_source_is_found_in_the_local_perseus_clone(tmp_path):
    """Without data/perseus/, the Greek file is looked up in data/raw/canonical-greekLit/data/<group>/<work>/."""
    raw = tmp_path / "raw"
    target = raw / "data" / "tlg0062" / "tlg001" / "tlg0062.tlg001.perseus-grc2.xml"
    target.parent.mkdir(parents=True)
    target.write_text("<TEI/>", encoding="utf-8")
    found = find_greek_file("texts/tlg0062.tlg001/greek/tlg0062.tlg001.perseus-grc2.xml",
                            tmp_path / "no_perseus_here", raw)
    assert found == target


def test_missing_greek_source_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_greek_file("texts/tlg9999.tlg001/greek/tlg9999.tlg001.perseus-grc1.xml", tmp_path, tmp_path)


# ---------------------------------------------------------------------------
# Matching English sentences to Greek sentences
# ---------------------------------------------------------------------------

def test_group_sentences_matches_length_shares():
    """Greek 100 + 50 characters; English 40, 60, 50: the first two English sentences go with Greek 1."""
    assert group_sentences([100, 50], [40, 60, 50]) == [(0, 2), (2, 3)]


def test_group_sentences_gives_every_greek_sentence_at_least_one():
    assert group_sentences([10, 10, 10], [5, 5, 5]) == [(0, 1), (1, 2), (2, 3)]


def test_sentence_plan_modes():
    greek_two = "ὁ Περικλῆς εἶπε. οἱ δὲ ἐσίγησαν."
    assert sentence_plan(greek_two, "Pericles spoke. They fell silent.")[0] == "paired"
    assert sentence_plan("ὁ Περικλῆς εἶπε.", "Pericles spoke. He left.")[0] == "grouped"
    mode, greek, english = sentence_plan(greek_two, "Pericles spoke, and they fell silent.")
    assert mode == "whole"
    assert greek == [(0, len(greek_two))] and english == ["Pericles spoke, and they fell silent."]


# ---------------------------------------------------------------------------
# One paragraph at a time (monotone aligner)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def monotone():
    return results("monotone")


@pytest.fixture(scope="module")
def no_aligner():
    return results("none")


def test_tag_placed_correctly(monotone):
    result = monotone[Q_RIGHT]
    assert result["status"] == "scored" and result["mode"] == "paired"
    assert result["output"] == "the Pericles spoke <q>fine words</q>."
    assert result["score"]["tag_accuracy"] == 1.0
    assert result["citation"] == "1"


def test_gold_disagrees_with_the_pipeline(monotone):
    """The gold's <q> is before 'spoke' (11 letters in), the pipeline's before 'fine' (16): 1 of 2 right."""
    score = monotone[Q_GOLD_EARLIER]["score"]
    assert score["tag_accuracy"] == 0.5
    assert score["average_distance"] == 2.5           # (5 + 0) / 2
    assert score["misplaced_tags"] == [{"tag": "<q>", "reference_position": 11,
                                        "hypothesis_position": 16, "distance": 5}]


def test_more_english_sentences_are_grouped(monotone):
    """One Greek sentence, two English ones ('the Pericles spoke. departed then.'): grouped, then placed."""
    result = monotone[GROUPED]
    assert result["mode"] == "grouped"
    assert result["output"] == "the Pericles spoke. <q>departed then</q>."
    assert result["score"]["tag_accuracy"] == 1.0


def test_fewer_english_sentences_use_the_whole_block(monotone):
    """Two Greek sentences, one English: the whole paragraph is one unit."""
    result = monotone[WHOLE]
    assert result["mode"] == "whole"
    assert result["output"] == "the Pericles spoke, they then <q>hushed</q>."
    assert result["score"]["tag_accuracy"] == 1.0


def test_note_is_a_point_and_spaces_do_not_count(monotone):
    """The pipeline puts the note after 'Pericles' ('Pericles<note/> spoke'), the gold before 'spoke'
    ('Pericles <note/>spoke'): the same place once spaces are ignored. The note's content is not compared."""
    result = monotone[NOTE]
    assert result["output"] == 'the Pericles<note n="n1"/> spoke.'
    assert result["score"]["tag_accuracy"] == 1.0


def test_fixed_element_is_scored_before_its_replacement(monotone):
    """<label> is transliterated by the pipeline; scored as a wrap, it goes around the English word it was aligned to.
    (Names are translated by the model since the 2026-11-20 policy, so they are ordinary wraps and need no test here.)"""
    result = monotone[FIXED]
    assert result["output"] == 'the <label type="person">Pericles</label> spoke.'
    assert result["score"]["tag_accuracy"] == 1.0


def test_fixed_element_with_the_policy_unchanged_cannot_be_scored():
    """The pipeline's own policy writes the transliteration (Perikles), so the text differs from the gold."""
    result = results("monotone", POLICY_AS_IS)[FIXED]
    assert result["status"] == "text_differs"


def test_paragraph_without_tags_is_skipped(monotone):
    assert monotone[NO_TAGS]["status"] == "no_tags"


def test_paragraph_still_in_greek_is_untranslated(monotone):
    """translations.csv marks the file as partial; this paragraph was left in Greek."""
    assert monotone[UNTRANSLATED]["status"] == "untranslated"


def test_milestone_before_the_next_word(monotone):
    result = monotone[MILESTONE]
    assert result["output"] == 'the Pericles <milestone unit="section" n="3b"/>spoke.'
    assert result["score"]["tag_accuracy"] == 1.0


# ---------------------------------------------------------------------------
# Without an aligner
# ---------------------------------------------------------------------------

def test_block_that_cannot_be_placed_is_a_fallback(no_aligner):
    """Without word links <q> cannot be placed; its fallback is span-wise, so the block gets no score."""
    result = no_aligner[Q_RIGHT]
    assert result["status"] == "fallback"
    assert result["fallback_reason"] == "q:unaligned"
    assert "score" not in result


def test_points_without_aligner_go_to_the_sentence_end(no_aligner):
    """Their fallback is 'boundary': after 'spoke.', 5 letters after the gold position before 'spoke'
    (the full stop does not count: punctuation is ignored)."""
    for index in (NOTE, MILESTONE):
        score = no_aligner[index]["score"]
        assert score["tag_accuracy"] == 0.0
        assert score["average_distance"] == 5.0


def test_punctuation_counts_with_ignore_punctuation_off():
    """The same fallback with punctuation counted: 'spoke.' is 6 characters."""
    result = score_file(FILES[0], POLICY, get_aligner("none"), ignore_punctuation=False)[NOTE]
    assert result["score"]["average_distance"] == 6.0


# ---------------------------------------------------------------------------
# Whole files, summarised per aligner
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def runs():
    return evaluate(FILES, {"monotone": get_aligner("monotone"), "none": get_aligner("none")}, POLICY)


def test_summary_counts_tags_over_all_scored_blocks(runs):
    """monotone: 7 paragraphs scored, 12 gold tags, 11 exact (all but one <q>), 5 letters off in total."""
    summary = runs["monotone"]["summary"]
    assert summary["statuses"] == {"scored": 7, "no_tags": 1, "untranslated": 1}
    assert summary["tags"] == 12 and summary["correct"] == 11
    assert summary["tag_accuracy"] == pytest.approx(11 / 12)
    assert summary["average_distance"] == pytest.approx(5 / 12)
    assert summary["per_tag"] == {"q": {"correct": 7, "total": 8}, "note": {"correct": 1, "total": 1},
                                  "label": {"correct": 2, "total": 2}, "milestone": {"correct": 1, "total": 1}}
    assert summary["fallback_rate"] == 0.0
    assert summary["all_tags"] == 12 and summary["strict_accuracy"] == pytest.approx(11 / 12)


def test_strict_accuracy_counts_tags_of_fallback_blocks_as_wrong(runs):
    """none scores only 2 tags (both wrong), but the 5 blocks it could not place hold 10 more gold tags
    (four <q> and one <label>, 2 tags each): strict accuracy is over all 12."""
    summary = runs["none"]["summary"]
    assert summary["tags"] == 2 and summary["all_tags"] == 12
    assert summary["strict_accuracy"] == 0.0


def test_summary_per_mode_and_file(runs):
    summary = runs["monotone"]["summary"]
    assert {mode: group["blocks"] for mode, group in summary["by_mode"].items()} == \
        {"grouped": 1, "paired": 5, "whole": 1}
    assert list(summary["by_file"]) == ["test.test001.perseus-grc1.en.xml"]


def test_summary_reports_fallbacks_and_their_reasons(runs):
    """none: 5 paragraphs cannot be placed (four <q>, one <label>); of the 7 placeable ones that is 5/7."""
    summary = runs["none"]["summary"]
    assert summary["statuses"] == {"fallback": 5, "scored": 2, "no_tags": 1, "untranslated": 1}
    assert summary["fallback_rate"] == pytest.approx(5 / 7)
    assert summary["fallback_reasons"] == {"q:unaligned": 4, "label:unaligned": 1}


def test_files_with_different_structure_are_reported(tmp_path):
    """If the gold file has a different number of paragraphs, the file is reported, not scored."""
    gold = tmp_path / "gold.en.xml"
    gold.write_text('<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div><p>only one</p></div></body></text></TEI>',
                    encoding="utf-8")
    entry = dict(FILES[0], gold_path=gold, gold_file="gold.en.xml")
    result = score_file(entry, POLICY, get_aligner("monotone"))
    assert len(result) == 1 and result[0]["status"] == "structure_mismatch"


def test_fixed_as_wrap_changes_only_fixed_inline_elements():
    """Names become wraps; notes, references removed from the MT input (bibl) and blocks stay as they are."""
    data = {"tags": {
        "name": {"role": "inline", "treatment": "transliterate"},
        "num": {"role": "inline", "treatment": "keep"},
        "bibl": {"role": "inline", "treatment": "keep", "params": {"mt_input": "remove"}},
        "note": {"role": "inline", "treatment": "keep-subtree"},
        "speaker": {"role": "block", "treatment": "transliterate"},
    }}
    changed = fixed_as_wrap(data)["tags"]
    assert changed["name"]["treatment"] == "translate"
    assert changed["num"]["treatment"] == "translate"
    assert changed["bibl"]["treatment"] == "keep"
    assert changed["note"]["treatment"] == "keep-subtree"
    assert changed["speaker"]["treatment"] == "transliterate"
    assert data["tags"]["name"]["treatment"] == "transliterate"      # the original is not changed


# ---------------------------------------------------------------------------
# The "sentence" baseline
# ---------------------------------------------------------------------------

def test_with_wrap_fallback_sets_the_fallback_of_wrap_elements_only():
    data = {"default": {"role": "inline", "treatment": "translate"},
            "tags": {"q": {"role": "inline", "treatment": "translate", "params": {"anchor": "left"}},
                     "note": {"role": "inline", "treatment": "keep-subtree"},
                     "p": {"role": "block", "treatment": "translate"}}}
    changed = with_wrap_fallback(data, "sentence")
    assert changed["tags"]["q"]["params"] == {"anchor": "left", "fallback": "sentence"}
    assert changed["default"]["params"] == {"fallback": "sentence"}
    assert "params" not in changed["tags"]["note"] and "params" not in changed["tags"]["p"]
    assert data["tags"]["q"]["params"] == {"anchor": "left"}           # the original is not changed


@pytest.fixture(scope="module")
def sentence_baseline():
    aligner, policy = make_method("sentence")
    assert aligner.name == "none"
    return score_file(FILES[0], policy, aligner)


def test_sentence_baseline_places_every_block(sentence_baseline):
    """Without alignment, a wrap covers its whole English sentence: no block falls back."""
    statuses = [result["status"] for result in sentence_baseline]
    assert "fallback" not in statuses
    assert sentence_baseline[Q_RIGHT]["output"] == "<q>the Pericles spoke fine words.</q>"


def test_sentence_baseline_is_wrong_but_measured(sentence_baseline):
    """Gold 'spoke <q>fine words</q>.', baseline '<q>... fine words.</q>'. Without spaces and punctuation
    the gold <q> is at 16 and </q> at 25; the baseline <q> at 0 and </q> also at 25 (the full stop between
    the gold and the baseline </q> does not count): 1 of 2 right, (16 + 0) / 2 = 8 off."""
    score = sentence_baseline[Q_RIGHT]["score"]
    assert score["tag_accuracy"] == 0.5
    assert score["average_distance"] == 8.0
