"""Tag-placement evaluation: how well does the hybrid pipeline place the tags?

The gold set (data/gold/grc-en/, see docs/gold_set_handover.md) holds English
TEI files: each a translation of one Greek Perseus file, with exactly the same
tags, placed where they belong. Its index, translations.csv, lists each gold
file with its Greek source.

Tag accuracy compares character positions, so the pipeline must place its tags
into exactly the gold English text, not into its own translation. For every
text block (paragraph) of a gold file:

1. The Greek block and the gold block are paired by position: both files have
   the same structure, so the n-th block of one is the n-th of the other.
2. The pipeline's placement step (pipeline/detag.py, placement.py) gets the
   Greek block and the gold English text without its tags. The pipeline
   places tags sentence by sentence, so each Greek sentence needs its English:
   - "paired":  same number of sentences, paired one to one;
   - "grouped": the English has more sentences (the translator split a Greek
     sentence): consecutive English sentences are grouped, one group per Greek
     sentence, so that each group's share of the English length best matches
     its Greek sentence's share of the Greek length;
   - "whole":   the English has fewer sentences: the whole block is one unit.
3. The aligner links the words, the pipeline places and rebuilds the block,
   and the result is compared with the gold block with metrics.scores.score:
   tag accuracy, average distance, per tag type, misplaced / missing / extra.
   Positions are counted without spaces and (by default) without punctuation,
   so '</q>"' and '"</q>' are the same place: translators put quotation
   marks inside or outside <q> inconsistently.
   The headline number is the strict accuracy (summarise): correct tags over
   all gold tags of the placeable blocks, so every method is measured on the
   same tags; tag_accuracy only covers the blocks a method could place.
   A block the pipeline cannot place (it would fall back to span-wise
   translation) gets no score and counts in the fallback rate.

"Fixed" elements (kept or transliterated ones the model still sees: label,
speaker, term, foreign; names and numbers are translated by the model since
the 2026-11-20 policy and are ordinary wraps): the pipeline normally replaces
their English words with their own content (Pericles -> <label>Perikles</label>),
which would make the text differ from the gold. By default (as_wrap=True) the
policy is loaded with those elements treated as ordinary wrap elements, so
they are placed around the English words they were aligned to and scored
"before the replacement"; the replacement itself is deterministic.

Usage: see scripts/eval_placement.py, or

    from tei_translate.metrics.placement_eval import evaluate, load_index
    from tei_translate.align import get_aligner

    files = load_index("data/gold/grc-en")
    runs = evaluate(files, {"monotone": get_aligner("monotone")})
    runs["monotone"]["summary"]["tag_accuracy"]
"""

import copy
import csv
import re
from collections import Counter
from pathlib import Path

import yaml
from lxml import etree

from tei_translate.metrics.fragments import read_fragment
from tei_translate.metrics.scores import score
from tei_translate.pipeline.detag import detag, has_block_descendant
from tei_translate.pipeline.placement import Fallback, Layout, place, rebuild
from tei_translate.pipeline.policy import DEFAULT_POLICY, REPO_ROOT, Policy
from tei_translate.pipeline.sentences import split_sentences

DEFAULT_GOLD_DIR = REPO_ROOT / "data" / "gold" / "grc-en"
DEFAULT_PERSEUS_DIR = REPO_ROOT / "data" / "perseus"
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw" / "canonical-greekLit"
FIXED_TREATMENTS = ("keep", "transliterate")
GREEK_LETTERS = re.compile(r"[Ͱ-Ͽἀ-῿]")


# ---------------------------------------------------------------------------
# Reading the gold set
# ---------------------------------------------------------------------------

def find_greek_file(relative_path, perseus_dir=DEFAULT_PERSEUS_DIR, raw_dir=DEFAULT_RAW_DIR):
    """The Greek source file of a gold file.

    translations.csv gives its path under data/perseus/ (created by
    scripts/data/build_dataset.py). If that folder is missing, the same file
    is looked up in the local Perseus clone (data/raw/canonical-greekLit/,
    created by scripts/data/count_tags.py), where it sits in
    data/<text group>/<work>/.
    """
    path = Path(perseus_dir) / relative_path
    if path.exists():
        return path
    name = Path(relative_path).name                       # e.g. tlg0062.tlg001.perseus-grc2.xml
    group, work = name.split(".")[:2]
    raw = Path(raw_dir) / "data" / group / work / name
    if raw.exists():
        return raw
    raise FileNotFoundError(f"Greek source not found: {path} (nor {raw})")


def load_index(gold_dir=DEFAULT_GOLD_DIR, perseus_dir=DEFAULT_PERSEUS_DIR, raw_dir=DEFAULT_RAW_DIR):
    """The gold files listed in translations.csv, each with its Greek source.

    Returns a list of dicts: gold_file (name), gold_path, greek_path, status
    (complete / partial), translator.
    """
    gold_dir = Path(gold_dir)
    files = []
    with open(gold_dir / "translations.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            files.append({
                "gold_file": row["gold_file"],
                "gold_path": gold_dir / row["gold_file"],
                "greek_path": find_greek_file(row["greek_file"], perseus_dir, raw_dir),
                "status": row.get("status", ""),
                "translator": row.get("translator", ""),
            })
    return files


# ---------------------------------------------------------------------------
# The policy used for evaluation
# ---------------------------------------------------------------------------

def is_fixed_inline(spec):
    """True for a policy rule of an inline element whose content is kept or transliterated
    while the model still sees its words (a "fixed" element in pipeline/detag.py)."""
    params = spec.get("params") or {}
    return (spec.get("role", "inline") == "inline"
            and spec.get("treatment") in FIXED_TREATMENTS
            and params.get("mt_input", "source") != "remove")


def fixed_as_wrap(data):
    """A copy of the policy data with fixed inline elements turned into wrap elements (treatment translate).

    Their placement params (fallback, ...) are kept. Notes, empty markers and
    blocks are not changed.
    """
    data = copy.deepcopy(data)
    specs = list((data.get("tags") or {}).values()) + list(data.get("overrides") or [])
    for spec in specs:
        if is_fixed_inline(spec):
            spec["treatment"] = "translate"
    return data


def with_wrap_fallback(data, fallback):
    """A copy of the policy data where every wrap element (inline, treatment translate) uses the given fallback.

    Used for the "sentence" baseline: with fallback "sentence", a wrap element
    that cannot be placed covers its whole English sentence, instead of the
    block going span-wise.
    """
    data = copy.deepcopy(data)
    specs = list((data.get("tags") or {}).values()) + list(data.get("overrides") or [])
    if data.get("default"):
        specs.append(data["default"])
    for spec in specs:
        if spec.get("role", "inline") == "inline" and spec.get("treatment") == "translate":
            spec["params"] = dict(spec.get("params") or {}, fallback=fallback)
    return data


def load_policy(path=DEFAULT_POLICY, as_wrap=True, wrap_fallback=None):
    """The pipeline policy, by default with fixed elements scored as wraps (see the module docstring).

    wrap_fallback: if given (e.g. "sentence"), every wrap element uses that fallback.
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if as_wrap:
        data = fixed_as_wrap(data)
    if wrap_fallback:
        data = with_wrap_fallback(data, wrap_fallback)
    return Policy(data)


# ---------------------------------------------------------------------------
# Methods to compare: real aligners and baselines
# ---------------------------------------------------------------------------

BASELINES = {
    "none": "no word alignment; a tag that needs it takes its fallback (usually: the block is not placed)",
    "monotone": "no model; assumes the English words follow the order of the Greek ones",
    "sentence": "no word alignment; a tag that needs it covers its whole English sentence",
}


def make_method(name, as_wrap=True):
    """(aligner, policy) for a method name: an aligner name (ugarit, xlmr, ...) or the baseline "sentence"."""
    from tei_translate.align import get_aligner      # imported here: loading the registry is not needed otherwise
    if name == "sentence":
        return get_aligner("none"), load_policy(as_wrap=as_wrap, wrap_fallback="sentence")
    return get_aligner(name), load_policy(as_wrap=as_wrap)


# ---------------------------------------------------------------------------
# Blocks: finding and pairing them
# ---------------------------------------------------------------------------

def text_blocks(tree, policy):
    """Every text block (role block) inside <text>, in document order."""
    blocks = []
    for text in tree.xpath("//*[local-name()='text'][not(ancestor::*[local-name()='text'])]"):
        for elem in text.iter():
            if isinstance(elem.tag, str) and policy.classify(elem).role == "block":
                blocks.append(elem)
    return blocks


def is_scorable(block, policy):
    """True for a block the hybrid pipeline places: treatment translate, no blocks inside it."""
    return policy.classify(block).treatment == "translate" and not has_block_descendant(block, policy)


def citation(elem):
    """The citation of the textpart divs around elem, e.g. '1.12' (empty if there are none)."""
    numbers = [div.get("n") for div in elem.iterancestors()
               if etree.QName(div).localname == "div" and div.get("type") == "textpart"]
    return ".".join(n for n in reversed(numbers) if n)


def normalise(text):
    """Text with every run of whitespace turned into one space."""
    return " ".join(text.split())


def without_namespaces(elem):
    """A copy of elem and everything below it, with the namespace removed from every element name.

    A fresh copy is needed: renaming the elements in place is not enough,
    because lxml would still write the TEI namespace declaration of the
    surrounding document onto them. Attributes (including xml:lang) are kept.
    """
    if not isinstance(elem.tag, str):
        copy_ = copy.copy(elem)
        copy_.tail = elem.tail
        return copy_
    new = etree.Element(etree.QName(elem).localname, dict(elem.attrib))
    new.text, new.tail = elem.text, elem.tail
    for child in elem:
        new.append(without_namespaces(child))
    return new


def inner_xml(elem):
    """The content of an element as an XML fragment, without the element's own tags."""
    return (elem.text or "") + "".join(etree.tostring(child, encoding="unicode") for child in elem)


def is_point_with_content(elem, policy):
    """True for an element the pipeline moves as a single point although it has content:
    kept subtrees (notes) and elements left out of the MT input (bibl references)."""
    rule = policy.classify(elem)
    return rule.treatment == "keep-subtree" or rule.params.get("mt_input") == "remove"


def empty_points(block, policy):
    """Remove the content of notes and references inside block (changes it in place), keeping their attributes.

    For tag placement they are single points: their content is copied
    unchanged (checked by the pipeline's validator), only their position
    matters. Without this, a note in a different place would also move its
    text, and the whole block could no longer be compared with the gold.
    """
    for elem in list(block.iter()):
        if elem is not block and isinstance(elem.tag, str) and is_point_with_content(elem, policy):
            for child in list(elem):
                elem.remove(child)
            elem.text = None
    return block


# ---------------------------------------------------------------------------
# Matching English sentences to Greek sentences
# ---------------------------------------------------------------------------

def group_sentences(greek_lengths, english_lengths):
    """Group consecutive English sentences, one group per Greek sentence.

    Needs at least as many English sentences as Greek ones. Every group has at
    least one sentence, the groups keep their order and cover all sentences.
    The grouping chosen is the one where each group's share of the English
    length best matches its Greek sentence's share of the Greek length (the
    smallest sum of squared differences). Returns (start, end) index ranges
    into the English sentences.

    Example: Greek lengths [100, 50], English [40, 60, 50] gives [(0, 2), (2, 3)].
    """
    n, m = len(greek_lengths), len(english_lengths)
    if m < n:
        raise ValueError("fewer English than Greek sentences")
    greek_total, english_total = sum(greek_lengths) or 1, sum(english_lengths) or 1
    prefix = [0]
    for length in english_lengths:
        prefix.append(prefix[-1] + length)
    INF = float("inf")
    # cost[i][j]: best cost of giving the first i Greek sentences the first j English ones.
    cost = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    for i in range(1, n + 1):
        target = greek_lengths[i - 1] / greek_total
        for j in range(i, m - (n - i) + 1):
            for start in range(i - 1, j):
                if cost[i - 1][start] == INF:
                    continue
                share = (prefix[j] - prefix[start]) / english_total
                total = cost[i - 1][start] + (share - target) ** 2
                if total < cost[i][j]:
                    cost[i][j], back[i][j] = total, start
    groups, j = [], m
    for i in range(n, 0, -1):
        start = back[i][j]
        groups.append((start, j))
        j = start
    return groups[::-1]


def sentence_plan(greek_text, english_text):
    """How the English sentences go with the Greek ones: (mode, Greek sentence ranges, English strings).

    Modes: "paired" (same number, one to one), "grouped" (more English
    sentences, grouped per Greek sentence), "whole" (fewer English sentences:
    the whole block is one unit).
    """
    greek = split_sentences(greek_text)
    english = [english_text[s:e] for s, e in split_sentences(english_text)]
    if len(english) == len(greek):
        return "paired", greek, english
    if len(english) > len(greek):
        groups = group_sentences([e - s for s, e in greek], [len(sentence) for sentence in english])
        return "grouped", greek, [" ".join(english[a:b]) for a, b in groups]
    return "whole", [(greek[0][0], greek[-1][1])], [" ".join(english)]


# ---------------------------------------------------------------------------
# One block in, one block out
# ---------------------------------------------------------------------------

def place_block(greek_block, english_text, policy, aligner):
    """Let the pipeline place the Greek block's tags into the given English text.

    Works on a copy of the Greek block. Returns (mode, rebuilt block,
    placement counts). Raises Fallback if the pipeline cannot place the block.
    """
    block = copy.deepcopy(greek_block)
    detagged = detag(block, policy)
    mode, greek_sentences, english_sentences = sentence_plan(detagged.text, english_text)
    layout = Layout(detagged, greek_sentences, english_sentences)
    needed = sorted(layout.needs_alignment())
    pairs = [layout.pair(k) for k in needed]
    links = aligner.align(pairs) if pairs else []
    for k, sentence_links in zip(needed, links):
        layout.set_links(k, sentence_links)
    try:
        placed, counts = place(layout)
    except Fallback as fallback:
        fallback.mode = mode
        raise
    rebuild(block, layout.english, placed)
    return mode, block, counts


def score_block(greek_block, gold_block, policy, aligner, ignore_punctuation=True):
    """Place the tags of one Greek block into the gold block's English and score them.

    ignore_punctuation: passed to metrics.scores.score (spaces are always
    ignored); by default a tag on either side of a quotation mark or other
    punctuation counts as the same place.

    Returns a dict with a status and, when scored, the metrics.scores.score
    fields. Status:
    - "scored": placed, same text as the gold, placement scored;
    - "fallback": the pipeline could not place the block (reason in "fallback_reason");
    - "text_differs": the rebuilt text is not exactly the gold text, so no score;
    - "untranslated": the gold block still contains Greek (a partial gold file);
    - "aligner_error": the aligner failed (e.g. a sentence too long for it);
    - "no_text": the block has no text to translate;
    - "no_tags": the block has no tags inside it, so there is nothing to place.
    """
    result = {"status": None}
    english_text = detag(gold_block, policy).text
    if GREEK_LETTERS.search(english_text):
        result["status"] = "untranslated"
        return result
    greek_detagged = detag(greek_block, policy)
    if not split_sentences(greek_detagged.text) or not english_text.strip():
        result["status"] = "no_text"
        return result
    if not greek_detagged.all:
        result["status"] = "no_tags"          # nothing to place in this block
        return result
    reference = inner_xml(empty_points(without_namespaces(gold_block), policy))
    result["gold_tags"] = len(read_fragment(reference)[1])     # counted for every block, also fallbacks
    try:
        mode, output, counts = place_block(greek_block, english_text, policy, aligner)
    except Fallback as fallback:
        result.update(status="fallback", fallback_reason=fallback.reason, mode=fallback.mode)
        return result
    except Exception as error:               # e.g. a sentence longer than the aligner can read
        result.update(status="aligner_error", error=f"{type(error).__name__}: {error}")
        return result
    hypothesis = inner_xml(empty_points(without_namespaces(output), policy))
    fields = score(reference, hypothesis, ignore_whitespace=True, ignore_punctuation=ignore_punctuation)
    result.update(mode=mode, placements=dict(counts), output=hypothesis, score=fields,
                  status="scored" if fields["same_text"] else "text_differs")
    return result


def score_file(entry, policy, aligner, ignore_punctuation=True):
    """Score every block of one gold file. Returns one result dict per scorable block.

    entry: one item of load_index(). ignore_punctuation: see score_block.
    Blocks are paired by position; if the two
    files do not have the same number of blocks, one "structure_mismatch"
    result is returned for the whole file.
    """
    greek_blocks = text_blocks(etree.parse(str(entry["greek_path"])), policy)
    gold_blocks = text_blocks(etree.parse(str(entry["gold_path"])), policy)
    if len(greek_blocks) != len(gold_blocks):
        return [{"id": entry["gold_file"], "gold_file": entry["gold_file"], "status": "structure_mismatch",
                 "error": f"{len(greek_blocks)} Greek blocks but {len(gold_blocks)} gold blocks"}]
    results = []
    for index, (greek_block, gold_block) in enumerate(zip(greek_blocks, gold_blocks)):
        if not is_scorable(greek_block, policy):
            continue
        result = {"id": f"{entry['gold_file']}:{citation(greek_block)}:{index}",
                  "gold_file": entry["gold_file"], "citation": citation(greek_block)}
        result.update(score_block(greek_block, gold_block, policy, aligner, ignore_punctuation))
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Many files, several aligners
# ---------------------------------------------------------------------------

def aggregate(results):
    """Tag accuracy, average distance and per-tag counts over the scored results.

    Totals over all tags (micro average): tag accuracy = all correctly placed
    tags / all gold tags; average distance = total distance / all tags that
    have a position in the output.
    """
    correct = total = paired = 0
    distance = 0.0
    per_tag = {}
    for result in results:
        fields = result["score"]
        correct += fields["correct_count"]
        total += fields["reference_tag_count"]
        n_paired = fields["reference_tag_count"] - len(fields["missing_tags"])
        paired += n_paired
        if fields["average_distance"] is not None:
            distance += fields["average_distance"] * n_paired
        for name, counts in fields["per_tag"].items():
            entry = per_tag.setdefault(name, {"correct": 0, "total": 0})
            entry["correct"] += counts["correct"]
            entry["total"] += counts["total"]
    return {
        "blocks": len(results),
        "tags": total,
        "correct": correct,
        "tag_accuracy": correct / total if total else None,
        "average_distance": distance / paired if paired else None,
        "per_tag": per_tag,
    }


def grouped_by(results, field):
    """{value of field: aggregate of the results with that value}, sorted by value."""
    groups = {}
    for result in results:
        groups.setdefault(result.get(field) or "unknown", []).append(result)
    return {value: aggregate(group) for value, group in sorted(groups.items())}


def summarise(results):
    """Summary of one aligner's results: statuses, fallback rate and reasons, scores overall,
    per sentence mode and per gold file."""
    statuses = Counter(result["status"] for result in results)
    scored = [result for result in results if result["status"] == "scored"]
    reasons = Counter(result["fallback_reason"] for result in results if result["status"] == "fallback")
    placeable = statuses["scored"] + statuses["fallback"] + statuses["text_differs"]
    # Strict accuracy: over every gold tag in the placeable blocks; tags in blocks
    # that could not be placed or compared count as wrong. Unlike tag_accuracy
    # (scored blocks only), every aligner is measured on the same tags. Blocks
    # where the aligner failed count too, otherwise a failing aligner would get
    # a smaller denominator and a higher score.
    all_tags = sum(result.get("gold_tags", 0) for result in results
                   if result["status"] in ("scored", "fallback", "text_differs", "aligner_error"))
    summary = aggregate(scored)
    summary.update(
        items=len(results),
        statuses=dict(statuses),
        all_tags=all_tags,
        strict_accuracy=summary["correct"] / all_tags if all_tags else None,
        fallback_rate=statuses["fallback"] / placeable if placeable else None,
        fallback_reasons=dict(reasons),
        by_mode=grouped_by(scored, "mode"),
        by_file=grouped_by(scored, "gold_file"),
    )
    return summary


def evaluate(files, aligners, policy=None, policies=None, ignore_punctuation=True):
    """Score every gold file with every aligner.

    files: from load_index(). aligners: {name: aligner object} (e.g. from
    tei_translate.align.get_aligner, or the aligner of make_method). policy:
    defaults to load_policy(). policies: optional {name: policy} for methods
    that need their own policy (the "sentence" baseline). ignore_punctuation:
    see score_block.
    Returns {aligner name: {"results": [...], "summary": {...}}}.
    """
    policy = policy or load_policy()
    policies = policies or {}
    runs = {}
    for name, aligner in aligners.items():
        results = []
        for entry in files:
            results += score_file(entry, policies.get(name, policy), aligner, ignore_punctuation)
        runs[name] = {"results": results, "summary": summarise(results)}
    return runs
