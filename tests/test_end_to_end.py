"""Tests for src/tei_translate/metrics/end_to_end.py (question 3: translation and tags together).

Uses the hand-made gold set of the placement evaluation
(tests/fixtures/placement_eval/, see its README): one Greek file and its
gold translation, nine paragraphs. No model is needed: the "identity" engine
returns the Greek unchanged, and WordEngine below translates word by word with
a small dictionary (the gold English has the same words in the same order), so
its output is close to the gold. The "monotone" aligner links the words in order.
"""

import re
from pathlib import Path

import pytest
from lxml import etree

from tei_translate.align import get_aligner
from tei_translate.engines import get_engine
from tei_translate.metrics.end_to_end import (
    block_fragment, evaluate_file, is_untranslated, select_units, summarise, truncate,
)
from tei_translate.metrics.placement_eval import load_index, load_policy, text_blocks
from tei_translate.pipeline.document import load_pair

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "placement_eval"
FILES = load_index(FIXTURES / "gold", FIXTURES / "perseus")
POLICY = load_policy(as_wrap=False)          # the pipeline's own policy, as in the real evaluation
PAIR = load_pair()
WORDS = {"ὁ": "the", "Περικλῆς": "Pericles", "εἶπε": "spoke", "καλοὺς": "fine", "λόγους": "words",
         "ἀπῆλθεν": "departed", "δέ": "then", "δὲ": "then", "οἱ": "they", "ἐσίγησαν": "hushed"}
GREEK_WORD = re.compile(r"[Ͱ-Ͽἀ-῿]+")


def english_word(match):
    """The dictionary translation of one Greek word (unknown words stay as they are)."""
    return WORDS.get(match.group(0), match.group(0))


class WordEngine:
    """Translates word by word with WORDS; the Greek ano teleia (·) becomes a full stop."""

    name = "word-test"

    def translate(self, segments, src, tgt):
        return [GREEK_WORD.sub(english_word, segment).replace("·", ".") for segment in segments]


def parse(path):
    return etree.parse(str(path), etree.XMLParser(remove_blank_text=False))


# ---------------------------------------------------------------------------
# Choosing the blocks
# ---------------------------------------------------------------------------

def test_units_leave_out_the_untranslated_gold_paragraph():
    """Nine paragraphs; the 8th (index 7) is still Greek in the gold file, so it is not scored."""
    units = select_units(parse(FILES[0]["greek_path"]), parse(FILES[0]["gold_path"]), POLICY)
    assert [unit["index"] for unit in units] == [0, 1, 2, 3, 4, 5, 6, 8]
    assert units[0]["reference"] == "the Pericles spoke <q>fine words</q>."
    assert units[0]["greek_text"] == "ὁ Περικλῆς εἶπε καλοὺς λόγους."


def test_units_respect_max_blocks():
    units = select_units(parse(FILES[0]["greek_path"]), parse(FILES[0]["gold_path"]), POLICY, max_blocks=3)
    assert [unit["index"] for unit in units] == [0, 1, 2]


def test_note_content_is_left_out_of_the_fragments():
    """Notes are points: their content is copied unchanged by the pipeline and not scored."""
    units = select_units(parse(FILES[0]["greek_path"]), parse(FILES[0]["gold_path"]), POLICY)
    note_unit = next(unit for unit in units if unit["index"] == 3)
    assert note_unit["reference"] == 'the Pericles <note n="n1"/>spoke.'


def test_xml_lang_is_ignored_in_fragments():
    block = etree.fromstring('<p xmlns="http://www.tei-c.org/ns/1.0">a <q xml:lang="grc">b</q></p>')
    assert block_fragment(block, POLICY) == "a <q>b</q>"


def test_untranslated_allows_a_few_greek_letters():
    assert is_untranslated("ὁ Περικλῆς εἶπε.")
    assert not is_untranslated("He used the word λόγος for it, as everyone does.")
    assert not is_untranslated("…")


def test_truncate_keeps_the_first_blocks():
    tree = truncate(parse(FILES[0]["greek_path"]), POLICY, 4)
    assert len(text_blocks(tree, POLICY)) == 4


# ---------------------------------------------------------------------------
# Running the conditions
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def word_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("e2e")
    return evaluate_file(FILES[0], WordEngine(), get_aligner("monotone"), POLICY, PAIR,
                         ("plain", "hybrid", "spanwise"), out_dir=out), out


def test_every_condition_gives_one_output_per_unit(word_run):
    result, _ = word_run
    for condition in ("plain", "hybrid", "spanwise"):
        assert len(result["conditions"][condition]["hyps"]) == len(result["units"]) == 8


def test_plain_output_is_text_only(word_run):
    result, _ = word_run
    assert result["conditions"]["plain"]["hyps"][0] == "the Pericles spoke fine words."
    assert result["conditions"]["plain"]["checks"] is None


def test_hybrid_puts_the_tag_around_the_translated_words(word_run):
    result, _ = word_run
    assert result["conditions"]["hybrid"]["hyps"][0] == "the Pericles spoke <q>fine words</q>."


def test_tagged_conditions_write_their_tei_files(word_run):
    _, out = word_run
    assert (out / "hybrid" / "test.test001.perseus-grc1.en.xml").exists()
    assert (out / "spanwise" / "test.test001.perseus-grc1.en.xml").exists()


def test_max_blocks_translates_a_truncated_copy(tmp_path):
    result = evaluate_file(FILES[0], get_engine("identity"), get_aligner("monotone"), POLICY, PAIR,
                           ("hybrid",), max_blocks=2, out_dir=tmp_path)
    assert [unit["index"] for unit in result["units"]] == [0, 1]
    assert len(text_blocks(parse(tmp_path / "greek" / "test.test001.perseus-grc1.xml"), POLICY)) == 2
    assert all(result["conditions"]["hybrid"]["checks"].values())


def test_structure_mismatch_is_reported(tmp_path):
    gold = tmp_path / "gold.en.xml"
    gold.write_text('<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div><p>only one</p></div></body></text></TEI>',
                    encoding="utf-8")
    entry = dict(FILES[0], gold_path=gold, gold_file="gold.en.xml")
    result = evaluate_file(entry, get_engine("identity"), get_aligner("monotone"), POLICY, PAIR, ("hybrid",))
    assert "error" in result and "units" not in result


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------

def test_summary_of_the_tagged_conditions(word_run):
    """The tags are kept in every block (structure match 100%), the validator passes, and the
    word-by-word translation is close to the gold."""
    result, _ = word_run
    for condition in ("hybrid", "spanwise"):
        summary = summarise([result], condition)
        assert summary["blocks"] == 8
        assert summary["files"] == 1 and summary["files_valid"] == 1 and summary["failed_checks"] == {}
        assert summary["structure_match"] == 1.0
        assert summary["xml_accuracy"] == 1.0
        assert summary["chrf"] > 80 and summary["node_chrf"] > 80
        assert summary["comet"] is None
        assert list(summary["per_file"]) == ["test.test001.perseus-grc1.en.xml"]


def test_summary_of_plain_has_no_tag_scores(word_run):
    result, _ = word_run
    summary = summarise([result], "plain")
    assert summary["chrf"] > 80
    assert "node_chrf" not in summary and "files_valid" not in summary


def test_hybrid_summary_counts_placed_blocks(word_run):
    result, _ = word_run
    summary = summarise([result], "hybrid")
    assert summary["blocks_placed"] + summary["blocks_spanwise"] > 0


def test_identity_engine_scores_low_but_keeps_the_structure(tmp_path):
    """Greek output against English gold: chrF is low, but the tags and the validator are fine."""
    result = evaluate_file(FILES[0], get_engine("identity"), get_aligner("monotone"), POLICY, PAIR,
                           ("hybrid",), out_dir=tmp_path)
    summary = summarise([result], "hybrid")
    assert summary["chrf"] < 20
    assert summary["structure_match"] == 1.0 and summary["files_valid"] == 1


def test_comet_uses_the_given_scorer(word_run):
    """With a stand-in scorer (no model), COMET is the average of the per-block scores."""
    result, _ = word_run
    summary = summarise([result], "plain", use_comet=True, scorer=constant_scorer)
    assert summary["comet"] == pytest.approx(0.5)
    assert summary["per_file"]["test.test001.perseus-grc1.en.xml"]["comet"] == pytest.approx(0.5)


def constant_scorer(rows):
    """A stand-in COMET model: 0.5 for every row."""
    return [0.5] * len(rows)
