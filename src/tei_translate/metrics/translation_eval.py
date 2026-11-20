"""Translation quality of the MT engines (question 1 of the evaluation): chrF, BLEU and COMET.

The passages and translations come from a run of scripts/compare_engines.py
(outputs/compare/<timestamp>/translations.jsonl): Perseus Greek passages, each
with one or more English Perseus translations as references and the output of
every engine. This module only scores them, so a slow engine never has to run
again to get a new metric.

All three metrics look at the text only (tags are removed; the passages of
compare_engines.py are plain text anyway):
- chrF and BLEU: corpus level, several references per passage allowed
  (metrics.translation_scores);
- COMET (Unbabel/wmt22-comet-da): each passage against its best reference,
  then averaged (metrics.comet_score). It reads the Greek source too; the
  model was not trained on Ancient Greek, so it is a second opinion next to
  chrF, not the main number.

Usage: see scripts/eval_translation.py, or

    from tei_translate.metrics.translation_eval import load_run, score_engines
    samples, hyps, meta = load_run("outputs/compare/<run>")
    scores = score_engines(samples, hyps, use_comet=False)
    scores["madlad-3b"]["chrf"]
"""

import json
from pathlib import Path

from tei_translate.metrics.comet_score import DEFAULT_MODEL, comet_scores
from tei_translate.metrics.translation_scores import bleu, chrf

SAMPLE_KEYS = ("work", "label", "ref", "greek", "references")
PIVOT = " (pivot)"     # column suffix compare_engines.py uses for a chain engine's intermediate text


def load_run(run_dir):
    """The passages and translations of a compare_engines.py run.

    Returns (samples, hyps, meta): samples is a list of dicts (work, label,
    ref, greek, references); hyps is {engine name: [one translation per
    sample]}; meta is run.json (empty if missing). Pivot texts of chain
    engines are left out.
    """
    run_dir = Path(run_dir)
    with open(run_dir / "translations.jsonl", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    if not rows:
        raise ValueError(f"{run_dir / 'translations.jsonl'} is empty")
    meta_path = run_dir / "run.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    names = list(meta.get("engines") or [key for key in rows[0] if key not in SAMPLE_KEYS and not key.endswith(PIVOT)])
    samples = [{key: row[key] for key in SAMPLE_KEYS} for row in rows]
    hyps = {name: [row[name] for row in rows] for name in names}
    return samples, hyps, meta


def mean(values):
    """The average of a list, or None if it is empty."""
    return sum(values) / len(values) if values else None


def scores_for(samples, hypotheses, passage_comet=None):
    """chrF, BLEU and (if given) the average COMET of one engine on the given passages.

    passage_comet: the COMET score of each of these passages, in the same order, or None.
    """
    references = [sample["references"] for sample in samples]
    return {
        "passages": len(samples),
        "chrf": chrf(references, hypotheses),
        "bleu": bleu(references, hypotheses),
        "comet": mean(passage_comet) if passage_comet is not None else None,
    }


def works_in_order(samples):
    """The work ids of the samples, in the order they first appear, with their labels."""
    works = {}
    for sample in samples:
        works.setdefault(sample["work"], sample.get("label") or sample["work"])
    return works


def score_engines(samples, hyps, use_comet=True, comet_model=DEFAULT_MODEL, batch_size=16, scorer=None):
    """Score every engine, overall and per work.

    hyps: {engine name: translations}. use_comet: also compute COMET (needs
    pip install -e .[comet]; downloads the model the first time). scorer: for
    tests, a stand-in for the COMET model (see metrics.comet_score).
    Returns {engine: {"passages", "chrf", "bleu", "comet", "per_passage_comet",
    "per_work": {work id: {"label", "passages", "chrf", "bleu", "comet"}}}}.
    """
    works = works_in_order(samples)
    results = {}
    for name, hypotheses in hyps.items():
        if len(hypotheses) != len(samples):
            raise ValueError(f"{name}: {len(hypotheses)} translations for {len(samples)} passages")
        passage_comet = None
        if use_comet:
            passage_comet = comet_scores([sample["greek"] for sample in samples],
                                         [sample["references"] for sample in samples],
                                         hypotheses, comet_model, batch_size, scorer)
        result = scores_for(samples, hypotheses, passage_comet)
        result["per_passage_comet"] = passage_comet
        result["per_work"] = {}
        for work, label in works.items():
            indexes = [i for i, sample in enumerate(samples) if sample["work"] == work]
            work_comet = [passage_comet[i] for i in indexes] if passage_comet is not None else None
            result["per_work"][work] = dict(scores_for([samples[i] for i in indexes],
                                                       [hypotheses[i] for i in indexes], work_comet), label=label)
        results[name] = result
    return results
