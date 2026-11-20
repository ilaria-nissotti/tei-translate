"""COMET: a neural translation-quality metric (Rei et al. 2022), computed on the text only.

COMET reads the source (Greek), the output and a reference translation, and
predicts how a human would rate the output. Unlike chrF and BLEU, it rewards
a translation with the right meaning in different words. Scores are usually
between 0 and 1; higher is better.

As with chrF and BLEU, tags are removed first (fragments.strip_tags), so
COMET scores only the translation, as Song et al. (2025) do ("Content-COMET").
COMET compares with one reference at a time: when a passage has several
reference translations, it is scored against each and the best score is
kept, the same idea as chrF, which uses the best-matching reference.

COMET needs PyTorch and downloads a model (about 2.3 GB) the first time, so
it is an optional extra, and this file is separate from translation_scores.py
so that importing the other metrics does not load PyTorch:

    pip install -e .[comet]

Usage (once the package is installed):

    from tei_translate.metrics.comet_score import comet

    sources    = ['<p>ὁ <name>Περικλῆς</name> εἶπε.</p>']
    references = [['<p>Pericles spoke.</p>', '<p>And Pericles said so.</p>']]   # 2 translations
    hypotheses = ['<p>Pericles said.</p>']
    comet(sources, references, hypotheses)    # one number for the whole test set

Caveat for the report: COMET's encoder (XLM-RoBERTa) was trained on Modern,
not Ancient Greek, so its use of the source is unreliable.
"""

from tei_translate.metrics.fragments import strip_tags
from tei_translate.metrics.translation_scores import as_list, check_inputs

DEFAULT_MODEL = "Unbabel/wmt22-comet-da"

# Loaded models, so a model is read from disk only once per run: {name: model}.
LOADED_MODELS = {}


# ---------------------------------------------------------------------------
# Preparing the input
# ---------------------------------------------------------------------------

def comet_rows(sources, references, hypotheses):
    """One COMET input row per (passage, reference), with tags removed.

    Returns (rows, owners): rows is a list of {"src", "mt", "ref"} dicts, the
    format COMET takes; owners[i] is the passage that row i belongs to. A
    passage with three references gives three rows.
    """
    check_inputs(references, hypotheses)
    if len(sources) != len(hypotheses):
        raise ValueError(f"{len(sources)} sources but {len(hypotheses)} hypotheses")
    rows, owners = [], []
    for passage, (source, refs, hypothesis) in enumerate(zip(sources, references, hypotheses)):
        src_text, mt_text = strip_tags(source), strip_tags(hypothesis)
        for ref in as_list(refs):
            rows.append({"src": src_text, "mt": mt_text, "ref": strip_tags(ref)})
            owners.append(passage)
    return rows, owners


def best_per_passage(row_scores, owners, number_of_passages):
    """For each passage, the highest score among its rows (its best reference)."""
    best = [None] * number_of_passages
    for score, passage in zip(row_scores, owners):
        if best[passage] is None or score > best[passage]:
            best[passage] = score
    return best


# ---------------------------------------------------------------------------
# Running the model
# ---------------------------------------------------------------------------

def load_model(model_name=DEFAULT_MODEL):
    """Download (the first time) and load a COMET model; later calls reuse it."""
    if model_name not in LOADED_MODELS:
        from comet import download_model, load_from_checkpoint   # imported here: needs PyTorch
        LOADED_MODELS[model_name] = load_from_checkpoint(download_model(model_name))
    return LOADED_MODELS[model_name]


def predict_with_model(rows, model_name=DEFAULT_MODEL, batch_size=16):
    """COMET scores for a list of rows, on the GPU if there is one."""
    import torch
    model = load_model(model_name)
    gpus = 1 if torch.cuda.is_available() else 0
    output = model.predict(rows, batch_size=batch_size, gpus=gpus, progress_bar=False)
    return list(output.scores)


# ---------------------------------------------------------------------------
# The metric
# ---------------------------------------------------------------------------

def comet_scores(sources, references, hypotheses, model_name=DEFAULT_MODEL, batch_size=16, scorer=None):
    """COMET score of each passage (best reference), in the order given.

    sources: the Greek inputs; references: one item per passage, either one
    reference (string) or a list of references; hypotheses: the outputs.
    All are XML fragments (tags are removed here).

    scorer is for testing: a function that takes the rows and returns one
    score per row, used instead of the real model.
    """
    rows, owners = comet_rows(sources, references, hypotheses)
    if not rows:
        return []
    if scorer is None:
        row_scores = predict_with_model(rows, model_name, batch_size)
    else:
        row_scores = scorer(rows)
    return best_per_passage(row_scores, owners, len(hypotheses))


def comet(sources, references, hypotheses, model_name=DEFAULT_MODEL, batch_size=16, scorer=None):
    """COMET of the whole test set: the average of the passages' scores. None if empty.

    Same input as comet_scores. Each passage is scored against its best
    reference, then the scores are averaged (COMET's usual system score).
    """
    scores = comet_scores(sources, references, hypotheses, model_name, batch_size, scorer)
    if not scores:
        return None
    return sum(scores) / len(scores)
