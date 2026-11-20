"""Tests for src/tei_translate/metrics/placement_eval.py (scoring tag placement against the gold set).

Run from the repository root (after pip install -e .[dev]):

    pytest tests/test_placement_eval.py -v

The gold items are hand-made (tests/fixtures/placement_eval/gold.jsonl), in the
format of docs/gold_set_handover.md. They use English sentences with the same
words in the same order as the Greek, so the "monotone" test aligner links the
words exactly and the right placement is known in advance. The "none" aligner
links nothing, so tags that need alignment take their fallback. Neither needs
a model. Every expected value below is worked out by hand from the gold.

How pytest works is explained at the top of tests/test_metrics.py.
"""

from pathlib import Path

import pytest
from lxml import etree

from tei_translate.align import get_aligner
from tei_translate.metrics.placement_eval import (
    ReplayEngine, evaluate, fixed_as_wrap, gold_fragment, load_gold, load_policy, run_item, without_namespaces,
)
from tei_translate.pipeline.document import load_pair

GOLD = Path(__file__).resolve().parent / "fixtures" / "placement_eval" / "gold.jsonl"
ITEMS = {item["id"]: item for item in load_gold(GOLD)}
PAIR = load_pair()
POLICY = load_policy()                       # names etc. scored as wraps (the default)
POLICY_AS_IS = load_policy(as_wrap=False)    # the pipeline's policy unchanged


def run(item_id, aligner="monotone", policy=POLICY):
    """Run one gold item through the hybrid pipeline and score it."""
    return run_item(ITEMS[item_id], get_aligner(aligner), policy, PAIR)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def test_load_gold_reads_every_item():
    assert list(ITEMS) == ["test:q_right", "test:q_gold_wider", "test:name_fixed",
                           "test:milestone", "test:split_mismatch"]


def test_replay_engine_returns_the_gold_english():
    """Sentences are matched with whitespace normalised; unknown pieces come back unchanged and are recorded."""
    engine = ReplayEngine({"ὁ Περικλῆς εἶπε.": "Pericles spoke."})
    assert engine.translate(["ὁ  Περικλῆς\n εἶπε.", "οἱ δέ"], "grc", "en") == ["Pericles spoke.", "οἱ δέ"]
    assert engine.missing == ["οἱ δέ"]


def test_fixed_as_wrap_changes_only_fixed_inline_elements():
    """Names become wraps; notes, references removed from the MT input (bibl) and blocks stay as they are."""
    data = {"tags": {
        "name": {"role": "inline", "treatment": "transliterate"},
        "num": {"role": "inline", "treatment": "keep"},
        "bibl": {"role": "inline", "treatment": "keep", "params": {"mt_input": "remove"}},
        "note": {"role": "inline", "treatment": "keep-subtree"},
        "speaker": {"role": "block", "treatment": "transliterate"},
    }, "overrides": [{"tag": "name", "attr": {"type": "ethnic"}, "role": "inline", "treatment": "translate"}]}
    changed = fixed_as_wrap(data)["tags"]
    assert changed["name"]["treatment"] == "translate"
    assert changed["num"]["treatment"] == "translate"
    assert changed["bibl"]["treatment"] == "keep"
    assert changed["note"]["treatment"] == "keep-subtree"
    assert changed["speaker"]["treatment"] == "transliterate"
    assert data["tags"]["name"]["treatment"] == "transliterate"      # the original is not changed


def test_gold_given_with_its_block_element_is_unwrapped():
    assert gold_fragment('<p>the <q>fine words</q>.</p>', "p") == "the <q>fine words</q>."
    assert gold_fragment("the <q>fine words</q>.", "p") == "the <q>fine words</q>."


def test_without_namespaces_removes_the_tei_namespace():
    root = etree.fromstring('<TEI xmlns="http://www.tei-c.org/ns/1.0"><p>a <q n="1">b</q> c</p></TEI>')
    clean = without_namespaces(root[0])
    assert etree.tostring(clean, encoding="unicode") == '<p>a <q n="1">b</q> c</p>'


# ---------------------------------------------------------------------------
# One item at a time
# ---------------------------------------------------------------------------

def test_tag_placed_correctly():
    result = run("test:q_right")
    assert result["status"] == "scored"
    assert result["output"] == "the Pericles spoke <q>fine words</q>."
    assert result["score"]["tag_accuracy"] == 1.0
    assert result["score"]["average_distance"] == 0.0


def test_gold_disagrees_with_the_pipeline():
    """The gold's <q> is before 'spoke' (position 13), the pipeline's before 'fine' (19): 1 of 2 tags right."""
    score = run("test:q_gold_wider")["score"]
    assert score["tag_accuracy"] == 0.5
    assert score["average_distance"] == 3.0          # (6 + 0) / 2
    assert score["misplaced_tags"] == [{"tag": "<q>", "reference_position": 13,
                                        "hypothesis_position": 19, "distance": 6}]


def test_name_is_scored_before_its_replacement():
    """With names scored as wraps, <name> is placed around the aligned word and the text stays the gold text."""
    result = run("test:name_fixed")
    assert result["status"] == "scored"
    assert result["output"] == 'the <name type="person">Pericles</name> spoke.'
    assert result["score"]["tag_accuracy"] == 1.0


def test_name_with_the_policy_unchanged_cannot_be_scored():
    """The pipeline's own policy writes the transliteration (Perikles), so the text differs from the gold."""
    result = run("test:name_fixed", policy=POLICY_AS_IS)
    assert result["status"] == "text_differs"
    assert "Perikles" in result["output"]


def test_milestone_before_the_next_word():
    result = run("test:milestone")
    assert result["output"] == 'the Pericles <milestone unit="section" n="1a"/>spoke.'
    assert result["score"]["tag_accuracy"] == 1.0


def test_milestone_without_aligner_falls_back_to_the_sentence_end():
    """Its fallback is 'boundary': placed at the end of the sentence, 6 characters after the gold position."""
    result = run("test:milestone", aligner="none")
    assert result["status"] == "scored"
    assert result["output"] == 'the Pericles spoke.<milestone unit="section" n="1a"/>'
    assert result["score"]["tag_accuracy"] == 0.0
    assert result["score"]["average_distance"] == 6.0


def test_block_that_cannot_be_placed_is_a_fallback():
    """Without an aligner <q> cannot be placed; its fallback is span-wise, so the block gets no score."""
    result = run("test:q_right", aligner="none")
    assert result["status"] == "fallback"
    assert result["fallback_reason"] == "q:unaligned"
    assert "score" not in result


def test_different_sentence_split_is_reported():
    """The gold lists one Greek sentence, the pipeline makes two: reported, not scored."""
    result = run("test:split_mismatch")
    assert result["status"] == "split_mismatch"
    assert result["pipeline_sentences"] == ["ὁ Περικλῆς εἶπε.", "οἱ δὲ ἐσίγησαν."]


# ---------------------------------------------------------------------------
# All items, summarised per aligner
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def runs():
    """Every gold item with both test aligners (run once for the tests below)."""
    items = list(ITEMS.values())
    return evaluate(items, {"monotone": get_aligner("monotone"), "none": get_aligner("none")}, POLICY, PAIR)


def test_summary_counts_tags_over_all_scored_blocks(runs):
    """monotone: 4 blocks scored, 7 gold tags, 6 placed exactly (all but the <q> of q_gold_wider)."""
    summary = runs["monotone"]["summary"]
    assert summary["statuses"] == {"scored": 4, "split_mismatch": 1}
    assert summary["tags"] == 7 and summary["correct"] == 6
    assert summary["tag_accuracy"] == pytest.approx(6 / 7)
    assert summary["average_distance"] == pytest.approx(6 / 7)      # one tag 6 characters off, 7 tags
    assert summary["per_tag"] == {"q": {"correct": 3, "total": 4}, "name": {"correct": 2, "total": 2},
                                  "milestone": {"correct": 1, "total": 1}}
    assert summary["fallback_rate"] == 0.0


def test_summary_reports_fallbacks_and_their_reasons(runs):
    """none: three blocks fall back (two <q>, one <name>); only the milestone block is scored."""
    summary = runs["none"]["summary"]
    assert summary["statuses"] == {"fallback": 3, "scored": 1, "split_mismatch": 1}
    assert summary["fallback_rate"] == pytest.approx(3 / 5)
    assert summary["fallback_reasons"] == {"q:unaligned": 2, "name:unaligned": 1}
    assert summary["tag_accuracy"] == 0.0


def test_summary_per_text_type(runs):
    assert list(runs["monotone"]["summary"]["by_type"]) == ["prose"]
    assert runs["monotone"]["summary"]["by_type"]["prose"]["tag_accuracy"] == pytest.approx(6 / 7)
