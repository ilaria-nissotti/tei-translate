"""Tests for the metrics in src/tei_translate/metrics/.

Run from the repository root (after pip install -e .[dev]):

    pytest                                  # all tests
    pytest tests/test_metrics.py -v         # these tests, one line each
    pytest -k structure                     # only tests with "structure" in the name

The test cases are the hand-made cases in tests/fixtures/metrics/ (described
in that folder's README). Each case becomes one test.
"""

import json
from pathlib import Path

import pytest
from sacrebleu.metrics import BLEU, CHRF

from tei_translate.metrics.fragments import strip_tags
from tei_translate.metrics.scores import score, is_valid_xml, xml_accuracy, same_structure, xml_matching
from tei_translate.metrics.translation_scores import chrf, bleu, reference_streams

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "metrics"


def load_cases(file_name):
    """The list of cases in a JSON file in tests/fixtures/metrics/."""
    return json.loads((FIXTURES / file_name).read_text(encoding="utf-8"))


def case_id(case):
    """The case's id, used as the test's name (e.g. test_placement[08_span_too_wide])."""
    return case["id"]


PLACEMENT_CASES = load_cases("cases.json")
STRUCTURE_CASES = load_cases("structure_cases.json")
TRANSLATION_CASES = load_cases("translation_cases.json")


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
        return sorted(got, key=as_sort_key) == sorted(expected, key=as_sort_key)
    return got == expected


# ---------------------------------------------------------------------------
# Tag placement (cases.json)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", PLACEMENT_CASES, ids=case_id)
def test_placement(case):
    """score() gives every expected field: tag accuracy, distance, tag lists, per tag."""
    result = score(case["reference"], case["hypothesis"])
    wrong = {field: {"expected": expected, "got": result.get(field)}
             for field, expected in case["expected"].items()
             if not same_value(result.get(field), expected)}
    assert not wrong, f"{case['description']}\nFields that differ: {wrong}"


# ---------------------------------------------------------------------------
# Structure (structure_cases.json)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", STRUCTURE_CASES, ids=case_id)
def test_structure(case):
    """is_valid_xml and same_structure give the expected True/False."""
    expected = case["expected"]
    got = {"valid_xml": is_valid_xml(case["hypothesis"]),
           "same_structure": same_structure(case["greek"], case["hypothesis"])}
    assert got == expected, case["description"]


def test_xml_accuracy_over_all_cases():
    """xml_accuracy is the share of valid outputs (17 of 20 = 0.85)."""
    expected = sum(case["expected"]["valid_xml"] for case in STRUCTURE_CASES) / len(STRUCTURE_CASES)
    assert xml_accuracy([case["hypothesis"] for case in STRUCTURE_CASES]) == pytest.approx(expected)


def test_xml_matching_over_all_cases():
    """xml_matching is the share of outputs with the input's structure (8 of 20 = 0.40)."""
    expected = sum(case["expected"]["same_structure"] for case in STRUCTURE_CASES) / len(STRUCTURE_CASES)
    sources = [case["greek"] for case in STRUCTURE_CASES]
    hypotheses = [case["hypothesis"] for case in STRUCTURE_CASES]
    assert xml_matching(sources, hypotheses) == pytest.approx(expected)


def test_xml_matching_refuses_lists_of_different_length():
    with pytest.raises(ValueError):
        xml_matching(["<a/>"], [])


def test_structure_metrics_on_empty_list():
    assert xml_accuracy([]) is None
    assert xml_matching([], []) is None


# ---------------------------------------------------------------------------
# Translation (translation_cases.json)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", TRANSLATION_CASES, ids=case_id)
def test_strip_tags(case):
    """strip_tags gives the hand-written plain text of every reference and the hypothesis."""
    assert [strip_tags(ref) for ref in case["references"]] == case["reference_texts"]
    assert strip_tags(case["hypothesis"]) == case["hypothesis_text"]


def test_reference_streams_layout():
    """Per-passage references are turned into sacrebleu's layout, padded with None."""
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
    expected = metric.corpus_score(hyp_texts, padded_reference_texts(TRANSLATION_CASES)).score
    assert function(references, hypotheses) == pytest.approx(expected)


def several_references_case():
    """The translation case with more than one reference (Thucydides 1.1.1)."""
    return next(case for case in TRANSLATION_CASES if len(case["references"]) > 1)


def test_chrf_uses_best_reference():
    """With several references, chrF equals the score against the best single one."""
    case = several_references_case()
    hyp = [case["hypothesis"]]
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
        chrf(["a reference"], [])


def test_translation_scores_refuse_passage_without_reference():
    with pytest.raises(ValueError):
        chrf([[]], ["a hypothesis"])


def test_translation_scores_on_empty_list():
    assert chrf([], []) is None
    assert bleu([], []) is None
