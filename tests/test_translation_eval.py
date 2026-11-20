"""Tests for src/tei_translate/metrics/translation_eval.py (question 1: chrF, BLEU, COMET per engine).

A tiny compare_engines.py run is written to a temporary folder: two works,
three passages, two engines ("good" copies the reference, "bad" does not).
COMET uses a stand-in scorer, so no model is needed.
"""

import json

import pytest

from tei_translate.metrics.translation_eval import load_run, score_engines, works_in_order

ROWS = [
    {"work": "w1", "label": "Work one", "ref": "1", "greek": "ὁ λόγος.", "references": ["The word."],
     "good": "The word.", "bad": "Something else entirely.", "chain": "x", "chain (pivot)": "ο λόγος."},
    {"work": "w1", "label": "Work one", "ref": "2", "greek": "ὁ ἵππος.", "references": ["The horse.", "A horse."],
     "good": "The horse.", "bad": "Nothing here.", "chain": "y", "chain (pivot)": "το άλογο."},
    {"work": "w2", "label": "Work two", "ref": "1", "greek": "ἡ θάλασσα.", "references": ["The sea."],
     "good": "The sea.", "bad": "No.", "chain": "z", "chain (pivot)": "η θάλασσα."},
]


@pytest.fixture
def run_dir(tmp_path):
    with open(tmp_path / "translations.jsonl", "w", encoding="utf-8") as f:
        for row in ROWS:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    meta = {"engines": {"good": {"model": "m/good"}, "bad": {"model": "m/bad"}, "chain": {"model": "a -> b"}}}
    (tmp_path / "run.json").write_text(json.dumps(meta), encoding="utf-8")
    return tmp_path


def test_load_run_reads_samples_and_engines_without_pivot_texts(run_dir):
    samples, hyps, meta = load_run(run_dir)
    assert len(samples) == 3 and samples[1]["references"] == ["The horse.", "A horse."]
    assert list(hyps) == ["good", "bad", "chain"]
    assert hyps["good"] == ["The word.", "The horse.", "The sea."]
    assert meta["engines"]["good"]["model"] == "m/good"


def test_load_run_without_run_json_takes_engines_from_the_columns(run_dir):
    (run_dir / "run.json").unlink()
    _, hyps, meta = load_run(run_dir)
    assert list(hyps) == ["good", "bad", "chain"] and meta == {}


def test_scores_overall_and_per_work(run_dir):
    samples, hyps, _ = load_run(run_dir)
    results = score_engines(samples, {"good": hyps["good"], "bad": hyps["bad"]}, use_comet=False)
    assert results["good"]["chrf"] == pytest.approx(100.0)
    assert results["bad"]["chrf"] < results["good"]["chrf"]
    assert results["good"]["comet"] is None
    assert list(results["good"]["per_work"]) == ["w1", "w2"]
    assert results["good"]["per_work"]["w1"]["passages"] == 2
    assert results["good"]["per_work"]["w2"]["label"] == "Work two"


def test_comet_per_passage_and_averaged(run_dir):
    """Stand-in scorer: 1.0 if the output equals the reference, else 0.0; each passage takes its best reference."""
    samples, hyps, _ = load_run(run_dir)
    results = score_engines(samples, {"good": hyps["good"], "bad": hyps["bad"]}, scorer=exact_match_scorer)
    assert results["good"]["per_passage_comet"] == [1.0, 1.0, 1.0]
    assert results["good"]["comet"] == 1.0
    assert results["bad"]["comet"] == 0.0
    assert results["good"]["per_work"]["w1"]["comet"] == 1.0


def test_wrong_number_of_translations_is_refused(run_dir):
    samples, _, _ = load_run(run_dir)
    with pytest.raises(ValueError):
        score_engines(samples, {"short": ["only one"]}, use_comet=False)


def test_works_keep_their_order():
    samples = [{"work": "b", "label": "B"}, {"work": "a", "label": "A"}, {"work": "b", "label": "B"}]
    assert works_in_order(samples) == {"b": "B", "a": "A"}


def exact_match_scorer(rows):
    """A stand-in COMET model: 1.0 when the output is exactly the reference."""
    return [1.0 if row["mt"] == row["ref"] else 0.0 for row in rows]
