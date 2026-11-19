"""Translation-quality metrics, computed on the text only (tags removed).

- chrf: character n-gram F-score (Popović 2015). Our main translation score.
- bleu: word n-gram precision (Papineni et al. 2002). Reported so results
  can be compared with other work.

Both are computed with sacrebleu (Post 2018) on the whole test set at once
(corpus level). Averaging per-passage scores would give a different, wrong
number. Scores are on sacrebleu's usual 0-100 scale.

Tags are removed with fragments.strip_tags before scoring. For outputs that
are not valid XML, everything of the form <...> is removed instead, so the
translation is still scored; broken XML is reported by xml_accuracy.

These are in a separate file from scores.py because the translation metrics
need extra libraries (sacrebleu now, COMET later). sacrebleu is a dependency
in pyproject.toml, so pip install -e . installs it.

Usage (once the package is installed):

    from tei_translate.metrics.translation_scores import chrf, bleu

    references = ['<said><label>Theo.</label> What matters do you mean?</said>',
                  ['Then Socrates said.', 'And Socrates spoke.']]   # 2 translations
    hypotheses = ['<said><label>Theo.</label> Which matters do you mean?</said>',
                  'Then Socrates spoke.']
    chrf(references, hypotheses)   # one number for the whole test set
"""

from sacrebleu.metrics import BLEU, CHRF

from tei_translate.metrics.fragments import strip_tags


# ---------------------------------------------------------------------------
# Preparing the input for sacrebleu
# ---------------------------------------------------------------------------

def as_list(references):
    """One passage's references as a list: a single reference becomes a list of one."""
    if isinstance(references, str):
        return [references]
    return list(references)


def reference_streams(references):
    """Turn per-passage references into the layout sacrebleu expects.

    references has one item per passage: a single reference (string) or a
    list of references (several translations of the same passage).
    sacrebleu wants the opposite layout: one list per "reference number",
    each as long as the test set. Passages with fewer references are padded
    with None, which sacrebleu ignores.

    Example: [['A1', 'A2'], 'B1'] gives [['A1', 'B1'], ['A2', None]].
    """
    per_passage = [[strip_tags(ref) for ref in as_list(refs)] for refs in references]
    most = max(len(refs) for refs in per_passage)
    streams = []
    for k in range(most):
        streams.append([refs[k] if k < len(refs) else None for refs in per_passage])
    return streams


def check_inputs(references, hypotheses):
    """Raise an error if the lists do not fit together or a passage has no reference."""
    if len(references) != len(hypotheses):
        raise ValueError(f"{len(references)} references but {len(hypotheses)} hypotheses")
    for i, refs in enumerate(references):
        if not as_list(refs):
            raise ValueError(f"passage {i} has no reference")


def corpus_score(metric, references, hypotheses):
    """Score the hypotheses against the references with a sacrebleu metric (tags removed).

    None if the lists are empty.
    """
    check_inputs(references, hypotheses)
    if not hypotheses:
        return None
    hyp_texts = [strip_tags(hyp) for hyp in hypotheses]
    return metric.corpus_score(hyp_texts, reference_streams(references)).score


# ---------------------------------------------------------------------------
# The metrics
# ---------------------------------------------------------------------------

def chrf(references, hypotheses):
    """chrF over the whole test set (0-100), tags removed.

    references: one item per passage, either one reference (string) or a
    list of references (several translations). With several, each passage
    is scored against its best-matching reference.
    hypotheses: the outputs, in the same order.

    sacrebleu's default settings: character n-grams up to 6, beta = 2.
    """
    return corpus_score(CHRF(), references, hypotheses)


def bleu(references, hypotheses):
    """BLEU over the whole test set (0-100), tags removed.

    Same input as chrf. With several references, n-grams can match any of them.
    sacrebleu's default settings: 13a tokenizer, n-grams up to 4, exponential smoothing.
    """
    return corpus_score(BLEU(), references, hypotheses)
