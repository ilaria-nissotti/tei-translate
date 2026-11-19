"""Tests for the metrics in src/tei_translate/metrics/.

Run from the repository root (after pip install -e .[dev]):

    pytest                                  # all tests
    pytest tests/test_metrics.py -v         # these tests, one line each
    pytest -k structure                     # only tests with "structure" in the name

The test cases are the hand-made cases in tests/fixtures/metrics/ (described
in that folder's README). Each case becomes one test.

How pytest works, in short (the same few tools are used throughout):
- pytest runs every function whose name starts with test_. Other functions
  (load_cases, same_value, ...) are helpers that the tests call.
- assert <condition>: the test passes if the condition is True, and fails
  otherwise. The text after the comma (assert x == y, "...") is printed when
  it fails, so we print the case's description there.
- @pytest.mark.parametrize("case", LIST, ids=case_id) above a test runs that
  test once for every item in LIST, passing the item as the argument case.
  So one test function checks every case in a JSON file, and each case is
  reported as its own test, named after its id: test_placement[08_span_too_wide].
- pytest.approx(x): "equal to x, allowing for tiny rounding differences".
  Needed when comparing decimal numbers such as 55.3500001 and 55.35.
- with pytest.raises(ValueError): the test passes only if the code inside
  raises a ValueError, i.e. it checks that wrong input is refused.
"""

import json
from pathlib import Path

import pytest
from sacrebleu.metrics import BLEU, CHRF

from tei_translate.metrics.fragments import strip_tags
from tei_translate.metrics.scores import score, is_valid_xml, xml_accuracy, same_structure, xml_matching
from tei_translate.metrics.translation_scores import (
    chrf, bleu, reference_streams, node_chrf, node_chrf_corpus, node_text_pairs, sentence_chrf,
)

# The folder with the JSON test cases: tests/fixtures/metrics/, found relative
# to this file, so the tests work from any folder.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "metrics"


# ---------------------------------------------------------------------------
# Loading the test cases
# ---------------------------------------------------------------------------

def load_cases(file_name):
    """The list of cases in a JSON file in tests/fixtures/metrics/."""
    return json.loads((FIXTURES / file_name).read_text(encoding="utf-8"))


def case_id(case):
    """The case's id, used as the test's name (e.g. test_placement[08_span_too_wide])."""
    return case["id"]


# All cases are loaded once, when pytest reads this file. Each list is then
# handed to @pytest.mark.parametrize below, which makes one test per case.
PLACEMENT_CASES = load_cases("cases.json")
STRUCTURE_CASES = load_cases("structure_cases.json")
TRANSLATION_CASES = load_cases("translation_cases.json")
NODE_CHRF_CASES = load_cases("node_chrf_cases.json")


# ---------------------------------------------------------------------------
# Comparing results with expected values
# ---------------------------------------------------------------------------

def as_sort_key(item):
    """A tag-list item as a string, so lists of dicts can be sorted."""
    return json.dumps(item, sort_keys=True)


def same_value(got, expected):
    """Compare a result with its expected value.

    Numbers may differ by 0.0001 (the JSON files round to 4 decimals) and the
    order of the tag lists does not matter.
    """
    if isinstance(expected, float) and isinstance(got, (int, float)):
        return abs(got - expected) <= 1e-4
    if isinstance(expected, list) and isinstance(got, list):
        # Sort both lists the same way, so [a, b] and [b, a] count as equal.
        return sorted(got, key=as_sort_key) == sorted(expected, key=as_sort_key)
    return got == expected


# ---------------------------------------------------------------------------
# Tag placement (cases.json): tag accuracy, average distance
# ---------------------------------------------------------------------------

# One test per case in cases.json (22 tests).
@pytest.mark.parametrize("case", PLACEMENT_CASES, ids=case_id)
def test_placement(case):
    """score() gives every expected field: tag accuracy, distance, tag lists, per tag."""
    result = score(case["reference"], case["hypothesis"])
    # Collect every field whose value differs from the expected one, e.g.
    # {"tag_accuracy": {"expected": 1.0, "got": 0.83}}. Empty if all are right.
    wrong = {field: {"expected": expected, "got": result.get(field)}
             for field, expected in case["expected"].items()
             if not same_value(result.get(field), expected)}
    assert not wrong, f"{case['description']}\nFields that differ: {wrong}"


# ---------------------------------------------------------------------------
# Structure (structure_cases.json): XML accuracy, XML matching
# ---------------------------------------------------------------------------

# One test per case in structure_cases.json (20 tests).
@pytest.mark.parametrize("case", STRUCTURE_CASES, ids=case_id)
def test_structure(case):
    """is_valid_xml and same_structure give the expected True/False."""
    expected = case["expected"]          # e.g. {"valid_xml": True, "same_structure": False}
    got = {"valid_xml": is_valid_xml(case["hypothesis"]),
           "same_structure": same_structure(case["greek"], case["hypothesis"])}
    assert got == expected, case["description"]


# The two corpus-level scores are the share of True values over all 20 cases.
# The expected share is counted from the cases' expected values.

def test_xml_accuracy_over_all_cases():
    """xml_accuracy is the share of valid outputs (17 of 20 = 0.85)."""
    # True counts as 1 and False as 0, so sum() counts the valid outputs.
    expected = sum(case["expected"]["valid_xml"] for case in STRUCTURE_CASES) / len(STRUCTURE_CASES)
    assert xml_accuracy([case["hypothesis"] for case in STRUCTURE_CASES]) == pytest.approx(expected)


def test_xml_matching_over_all_cases():
    """xml_matching is the share of outputs with the input's structure (8 of 20 = 0.40)."""
    expected = sum(case["expected"]["same_structure"] for case in STRUCTURE_CASES) / len(STRUCTURE_CASES)
    sources = [case["greek"] for case in STRUCTURE_CASES]
    hypotheses = [case["hypothesis"] for case in STRUCTURE_CASES]
    assert xml_matching(sources, hypotheses) == pytest.approx(expected)


# Wrong input must be refused with an error, not give a misleading score.

def test_xml_matching_refuses_lists_of_different_length():
    with pytest.raises(ValueError):
        xml_matching(["<a/>"], [])       # 1 source but 0 outputs


def test_structure_metrics_on_empty_list():
    assert xml_accuracy([]) is None
    assert xml_matching([], []) is None


# ---------------------------------------------------------------------------
# Translation (translation_cases.json): removing tags, chrF, BLEU
# ---------------------------------------------------------------------------
# chrF and BLEU come from sacrebleu, so their values are not worked out by
# hand. These tests check our own part: removing the tags, passing several
# references, and refusing wrong input.

# One test per case in translation_cases.json (7 tests).
@pytest.mark.parametrize("case", TRANSLATION_CASES, ids=case_id)
def test_strip_tags(case):
    """strip_tags gives the hand-written plain text of every reference and the hypothesis."""
    assert [strip_tags(ref) for ref in case["references"]] == case["reference_texts"]
    assert strip_tags(case["hypothesis"]) == case["hypothesis_text"]


def test_reference_streams_layout():
    """Per-passage references are turned into sacrebleu's layout, padded with None."""
    # Passage A has two translations, passage B one. sacrebleu wants one list
    # per "translation number": all 1st translations, then all 2nd ones.
    assert reference_streams([["A1", "A2"], "B1"]) == [["A1", "B1"], ["A2", None]]


def padded_reference_texts(cases):
    """The cases' plain reference texts in sacrebleu's layout, padded with None.

    Written separately from reference_streams, so the test does not just
    repeat the code it is testing.
    """
    most = max(len(case["reference_texts"]) for case in cases)
    streams = [[] for _ in range(most)]
    for case in cases:
        texts = case["reference_texts"] + [None] * (most - len(case["reference_texts"]))
        for k in range(most):
            streams[k].append(texts[k])
    return streams


# Runs twice: once with (chrf, CHRF()) and once with (bleu, BLEU()), named
# test_corpus_score_equals_sacrebleu_on_plain_text[chrf] and [bleu].
@pytest.mark.parametrize("function, metric", [(chrf, CHRF()), (bleu, BLEU())], ids=["chrf", "bleu"])
def test_corpus_score_equals_sacrebleu_on_plain_text(function, metric):
    """chrf/bleu on the XML give exactly sacrebleu's score on the hand-written plain texts.

    A passage with one reference is passed as a string, with several as a
    list, so both forms are tested.
    """
    references = [case["references"][0] if len(case["references"]) == 1 else case["references"]
                  for case in TRANSLATION_CASES]
    hypotheses = [case["hypothesis"] for case in TRANSLATION_CASES]
    hyp_texts = [case["hypothesis_text"] for case in TRANSLATION_CASES]
    # What sacrebleu gives on the plain texts written by hand ...
    expected = metric.corpus_score(hyp_texts, padded_reference_texts(TRANSLATION_CASES)).score
    # ... must equal what our function gives on the XML (tags removed by it).
    assert function(references, hypotheses) == pytest.approx(expected)


def several_references_case():
    """The translation case with more than one reference (Thucydides 1.1.1)."""
    return next(case for case in TRANSLATION_CASES if len(case["references"]) > 1)


def test_chrf_uses_best_reference():
    """With several references, chrF equals the score against the best single one."""
    case = several_references_case()
    hyp = [case["hypothesis"]]
    # Score against each translation on its own, and keep the best.
    best_single = max(chrf([ref], hyp) for ref in case["references"])
    assert chrf([case["references"]], hyp) == pytest.approx(best_single)


def test_bleu_several_references_at_least_best_single():
    """With several references, BLEU is at least as high as against any single one."""
    case = several_references_case()
    hyp = [case["hypothesis"]]
    best_single = max(bleu([ref], hyp) for ref in case["references"])
    assert bleu([case["references"]], hyp) >= best_single


def test_translation_scores_refuse_lists_of_different_length():
    with pytest.raises(ValueError):
        chrf(["a reference"], [])        # 1 reference but 0 outputs


def test_translation_scores_refuse_passage_without_reference():
    with pytest.raises(ValueError):
        chrf([[]], ["a hypothesis"])     # the passage's list of references is empty


def test_translation_scores_on_empty_list():
    assert chrf([], []) is None
    assert bleu([], []) is None


# ---------------------------------------------------------------------------
# Node-chrF (node_chrf_cases.json)
# ---------------------------------------------------------------------------
# Each case lists, written by hand, which texts should be paired ("pairs")
# and how many elements stay without a partner ("unpaired"). Some cases also
# give the score directly ("node_chrf"), where it is known by hand.

def cases_with(field, cases):
    """The cases whose expected values include field."""
    return [case for case in cases if field in case["expected"]]


# One test per case that lists "pairs" (15 of the 17; cases 16 and 17 have
# no pairs to check, only a score).
@pytest.mark.parametrize("case", cases_with("pairs", NODE_CHRF_CASES), ids=case_id)
def test_node_chrf_pairs(case):
    """Elements are paired as written by hand, with the right own texts and number unpaired."""
    got = node_text_pairs(case["reference"], case["hypothesis"])
    # Sorted, because the order in which the pairs are listed does not matter.
    # tuple(...): the JSON file stores each pair as a list, the function as a tuple.
    expected_pairs = sorted(tuple(pair) for pair in case["expected"]["pairs"])
    assert sorted(got["pairs"]) == expected_pairs, case["description"]
    assert got["unpaired"] == case["expected"]["unpaired"], case["description"]


# Same 15 cases: the score must follow from the hand-written pairs.
@pytest.mark.parametrize("case", cases_with("pairs", NODE_CHRF_CASES), ids=case_id)
def test_node_chrf_score_from_pairs(case):
    """node_chrf is the average of sacrebleu's chrF on the hand-written pairs, with 0 per unpaired element."""
    expected = case["expected"]
    # chrF for every expected pair, plus a 0 for every unpaired element ...
    scores = [sentence_chrf(ref, hyp) for ref, hyp in expected["pairs"]] + [0.0] * expected["unpaired"]
    # ... and node_chrf must be their average.
    assert node_chrf(case["reference"], case["hypothesis"]) == pytest.approx(sum(scores) / len(scores))


# One test per case that gives the score directly ("node_chrf").
@pytest.mark.parametrize("case", cases_with("node_chrf", NODE_CHRF_CASES), ids=case_id)
def test_node_chrf_known_score(case):
    """Cases whose score is known by hand: 100, 66.67 (one of three elements lost), 0, or None."""
    got = node_chrf(case["reference"], case["hypothesis"])
    expected = case["expected"]["node_chrf"]
    if expected is None:                 # nothing to compare (case 17)
        assert got is None
    else:
        assert got == pytest.approx(expected, abs=1e-4)


def test_node_chrf_corpus_is_average_over_passages():
    """node_chrf_corpus averages node_chrf over the passages, leaving out those with nothing to compare."""
    references = [case["reference"] for case in NODE_CHRF_CASES]
    hypotheses = [case["hypothesis"] for case in NODE_CHRF_CASES]
    scores = [node_chrf(ref, hyp) for ref, hyp in zip(references, hypotheses)]
    scores = [value for value in scores if value is not None]
    assert len(scores) == len(NODE_CHRF_CASES) - 1      # case 17 is left out
    assert node_chrf_corpus(references, hypotheses) == pytest.approx(sum(scores) / len(scores))


def test_sentence_chrf_two_empty_texts_are_identical():
    # sacrebleu gives 0 for two empty texts; we count them as identical (100).
    assert sentence_chrf("", "") == 100.0
    assert sentence_chrf("Theo.", "") == 0.0


def test_node_chrf_refuses_invalid_reference():
    with pytest.raises(ValueError):
        node_chrf("<said>broken", "<said>fine</said>")   # reference never closes <said>


def test_node_chrf_corpus_refuses_lists_of_different_length():
    with pytest.raises(ValueError):
        node_chrf_corpus(["<said>a</said>"], [])


def test_node_chrf_corpus_on_empty_list():
    assert node_chrf_corpus([], []) is None
