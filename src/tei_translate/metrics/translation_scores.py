"""Translation-quality metrics, computed on the text only (tags removed).

- chrf: character n-gram F-score (Popović 2015). Our main translation score.
- bleu: word n-gram precision (Papineni et al. 2002). Reported so results
  can be compared with other work.
- node_chrf / node_chrf_corpus: chrF per element, so it checks that the right
  words are inside each tag (Song et al. 2025). Unlike chrf and bleu, it
  needs a reference with the same tags as the output.

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

from tei_translate.metrics.fragments import (
    strip_tags, parse_fragment, all_elements, own_text, tag_signature,
)


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


# ---------------------------------------------------------------------------
# Node-chrF (Song et al. 2025)
# ---------------------------------------------------------------------------

SENTENCE_CHRF = CHRF()


def sentence_chrf(reference_text, hypothesis_text):
    """chrF (0-100) of one short text against one reference text.

    Two empty texts count as identical (100). sacrebleu itself gives 0 there,
    but for pairing elements two empty texts are a perfect match.
    """
    if not reference_text and not hypothesis_text:
        return 100.0
    return SENTENCE_CHRF.sentence_score(hypothesis_text, [reference_text]).score


def group_by_signature(elements):
    """The elements grouped by tag name and attributes: {signature: [elements in document order]}."""
    groups = {}
    for elem in elements:
        groups.setdefault(tag_signature(elem), []).append(elem)
    return groups


def best_match_pairs(ref_elems, hyp_elems):
    """Pair elements that have the same tag and attributes, best-matching texts first.

    Every possible reference/hypothesis pair gets the chrF of their own
    texts; the pair with the highest score is taken first, then the next
    best pair whose elements are both still free, and so on (on equal
    scores, earlier elements first). So when English word order differs,
    each name still pairs with the name it matches. Elements left over are
    unpaired. Returns (pairs, unpaired_ref, unpaired_hyp).
    """
    candidates = []
    for r, ref in enumerate(ref_elems):
        for h, hyp in enumerate(hyp_elems):
            candidates.append((-sentence_chrf(own_text(ref), own_text(hyp)), r, h))
    candidates.sort()

    pairs, used_ref, used_hyp = [], set(), set()
    for _, r, h in candidates:
        if r not in used_ref and h not in used_hyp:
            pairs.append((ref_elems[r], hyp_elems[h]))
            used_ref.add(r)
            used_hyp.add(h)
    unpaired_ref = [e for i, e in enumerate(ref_elems) if i not in used_ref]
    unpaired_hyp = [e for i, e in enumerate(hyp_elems) if i not in used_hyp]
    return pairs, unpaired_ref, unpaired_hyp


def node_text_pairs(reference, hypothesis):
    """The text pairs Node-chrF scores, and how many elements are unpaired.

    Returns {"pairs": [(reference text, hypothesis text), ...], "unpaired": n},
    or None if the hypothesis is not valid XML. Pairs where both texts are
    empty (e.g. two <milestone/>) are left out: there is nothing to compare.
    Unpaired elements (lost, extra or renamed tags) are counted, also when
    they are empty, because each of them scores 0.
    """
    ref_root = parse_fragment(reference)
    if ref_root is None:
        raise ValueError("the reference is not well-formed XML")
    hyp_root = parse_fragment(hypothesis)
    if hyp_root is None:
        return None

    ref_groups = group_by_signature(all_elements(ref_root))
    hyp_groups = group_by_signature(all_elements(hyp_root))
    text_pairs = []
    unpaired = 0
    for signature in ref_groups.keys() | hyp_groups.keys():
        pairs, unpaired_ref, unpaired_hyp = best_match_pairs(
            ref_groups.get(signature, []), hyp_groups.get(signature, []))
        for ref, hyp in pairs:
            ref_text, hyp_text = own_text(ref), own_text(hyp)
            if ref_text or hyp_text:
                text_pairs.append((ref_text, hyp_text))
        unpaired += len(unpaired_ref) + len(unpaired_hyp)
    return {"pairs": text_pairs, "unpaired": unpaired}


def node_chrf(reference, hypothesis):
    """Node-chrF of one passage (0-100): are the right words inside each tag?

    Elements with the same tag and attributes are paired (best-matching
    texts first). Each pair scores the chrF of the two elements' own texts;
    each unpaired element scores 0; the result is the average. Based on
    Song et al. (2025), who pair elements by position instead.

    The reference must have the same tags as the output should have (e.g. a
    hand-tagged Perseus translation). 0 if the hypothesis is not valid XML;
    None if there is nothing to compare (no text and no unpaired element).
    The rules and examples are in tests/fixtures/metrics/README.md.
    """
    details = node_text_pairs(reference, hypothesis)
    if details is None:
        return 0.0
    scores = [sentence_chrf(ref, hyp) for ref, hyp in details["pairs"]]
    scores += [0.0] * details["unpaired"]
    if not scores:
        return None
    return sum(scores) / len(scores)


def node_chrf_corpus(references, hypotheses):
    """Average Node-chrF over all passages (0-100).

    references and hypotheses are lists of XML fragments in the same order,
    one reference per passage. Passages with nothing to compare are left
    out. None if there is no passage to average.
    """
    if len(references) != len(hypotheses):
        raise ValueError(f"{len(references)} references but {len(hypotheses)} hypotheses")
    scores = [node_chrf(ref, hyp) for ref, hyp in zip(references, hypotheses)]
    scores = [value for value in scores if value is not None]
    if not scores:
        return None
    return sum(scores) / len(scores)
