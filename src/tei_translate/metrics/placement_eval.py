"""Tag-placement evaluation: how well does the hybrid pipeline place the tags?

Each gold item (data/gold/grc-en/gold.jsonl, format in docs/gold_set_handover.md)
holds a Greek block, a fixed English translation of it (one English sentence
per Greek sentence) and that English with the tags placed by hand ("gold").

For every item and every aligner:
1. The hybrid pipeline translates the block with a replay engine, which returns
   the gold English sentences. The output therefore has exactly the gold text,
   and only the tag positions can differ.
2. The output block is compared with the gold using metrics.scores.score:
   tag accuracy, average distance, per tag type, misplaced / missing / extra.
3. A block that the pipeline could not place (it fell back to span-wise
   translation) gets no placement score; it is counted as a fallback.

Names, numbers and other "fixed" elements: the pipeline normally replaces
their English words with their own content (Pericles -> <name>Perikles</name>),
which changes the text so it can no longer be compared with the gold. By
default (fixed_as_wrap=True) the policy is loaded with those elements treated
as ordinary wrap elements, so they are placed around the English words they
were aligned to, without the replacement: the placement is scored "before the
replacement", as the hand-over proposes. The replacement itself is
deterministic and needs no gold set.

Usage: see scripts/eval_placement.py, or

    from tei_translate.metrics.placement_eval import evaluate, load_gold, load_policy
    from tei_translate.align import get_aligner

    items = load_gold("data/gold/grc-en/gold.jsonl")
    runs = evaluate(items, {"monotone": get_aligner("monotone")})
    runs["monotone"]["summary"]["tag_accuracy"]
"""

import copy
import json
import tempfile
from collections import Counter
from pathlib import Path

import yaml
from lxml import etree

from tei_translate.metrics.scores import score
from tei_translate.pipeline.detag import detag
from tei_translate.pipeline.document import load_pair, translate_document
from tei_translate.pipeline.policy import DEFAULT_POLICY, Policy
from tei_translate.pipeline.sentences import split_sentences

TEI_NS = "http://www.tei-c.org/ns/1.0"
FIXED_TREATMENTS = ("keep", "transliterate")


# ---------------------------------------------------------------------------
# Reading the gold set
# ---------------------------------------------------------------------------

def load_gold(path):
    """The gold items in a JSON-lines file (one JSON object per line; blank lines skipped)."""
    items = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            items.append(json.loads(line))
    return items


def normalise(text):
    """Text with every run of whitespace turned into one space."""
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# The replay engine: makes the pipeline produce exactly the gold English
# ---------------------------------------------------------------------------

class ReplayEngine:
    """An MT engine that returns the gold English sentence for each Greek sentence.

    mapping: {Greek sentence: English sentence}. Sentences are compared with
    whitespace normalised. A segment that is not in the mapping is returned
    unchanged and recorded in `missing`; this happens only when a block falls
    back to span-wise translation, which sends pieces instead of sentences.
    """

    name = "replay"

    def __init__(self, mapping):
        self.mapping = {normalise(greek): english for greek, english in mapping.items()}
        self.missing = []

    def translate(self, segments, src, tgt):
        out = []
        for segment in segments:
            key = normalise(segment)
            if key in self.mapping:
                out.append(self.mapping[key])
            else:
                self.missing.append(segment)
                out.append(segment)
        return out


def replay_mapping(item):
    """{Greek sentence: English sentence} for a gold item."""
    greek, english = item["greek_sentences"], item["english_sentences"]
    if len(greek) != len(english):
        raise ValueError(f"{item['id']}: {len(greek)} Greek sentences but {len(english)} English ones")
    return dict(zip(greek, english))


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


def load_policy(path=DEFAULT_POLICY, as_wrap=True):
    """The pipeline policy, by default with fixed elements scored as wrap elements (see the module docstring)."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Policy(fixed_as_wrap(data) if as_wrap else data)


# ---------------------------------------------------------------------------
# One block in, one block out
# ---------------------------------------------------------------------------

def wrap_in_document(greek_block):
    """A minimal TEI document holding one Greek block, so the pipeline can translate it."""
    return (f'<TEI xmlns="{TEI_NS}"><text><body>'
            f'<div type="gold-item">{greek_block}</div>'
            f'</body></text></TEI>')


def item_block(tree):
    """The block element inside the gold-item div of a (translated) document."""
    found = tree.xpath("//*[local-name()='div'][@type='gold-item']/*")
    if not found:
        raise ValueError("no block found in the gold-item div")
    return found[0]


def without_namespaces(elem):
    """A copy of elem and everything below it, with the namespace removed from every element name.

    A fresh copy is needed: renaming the elements in place is not enough,
    because lxml would still write the TEI namespace declaration of the
    surrounding document onto them. Attributes (including xml:lang) are kept
    as they are. Comments and processing instructions are copied.
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


def pipeline_sentences(greek_block, policy):
    """The Greek sentences the pipeline will send for this block (whitespace normalised)."""
    block = item_block(etree.fromstring(wrap_in_document(greek_block)))
    text = detag(block, policy).text
    return [normalise(text[start:end]) for start, end in split_sentences(text)]


def gold_fragment(gold, block_tag):
    """The gold as the content of the block. A gold given with the block element around it is unwrapped."""
    root = etree.fromstring(f"<root>{gold}</root>")
    children = [child for child in root if isinstance(child.tag, str)]
    if (len(children) == 1 and etree.QName(children[0]).localname == block_tag
            and not (root.text or "").strip() and not (children[0].tail or "").strip()):
        return inner_xml(without_namespaces(children[0]))
    return gold


def translate_block(item, aligner, policy, pair):
    """Run the hybrid pipeline on the item's Greek block with the replay engine. Returns the pipeline's Result."""
    engine = ReplayEngine(replay_mapping(item))
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "item.xml"
        path.write_text(wrap_in_document(item["greek_block"]), encoding="utf-8")
        return translate_document(path, pair, engine=engine, policy=policy,
                                  placement="hybrid", aligner=aligner)


def run_item(item, aligner, policy, pair):
    """Translate one gold item and score its tag placement.

    Returns a dict with the item's id and type, a status and, when scored,
    the metrics.scores.score fields. Status:
    - "scored": placed in hybrid mode, same text as the gold, placement scored;
    - "fallback": the block went span-wise (reason in "fallback_reason"), no score;
    - "text_differs": the output text is not the gold text, so no score
      (should not happen with fixed elements scored as wraps);
    - "split_mismatch": the pipeline splits the Greek into different sentences
      than the gold item lists, so the replay cannot work (the item needs
      updating);
    - "not_hybrid": the block was not handled in hybrid mode at all.
    """
    result = {"id": item["id"], "type": item.get("type"), "status": None}
    expected = [normalise(sentence) for sentence in item["greek_sentences"]]
    actual = pipeline_sentences(item["greek_block"], policy)
    if actual != expected:
        result.update(status="split_mismatch", expected_sentences=expected, pipeline_sentences=actual)
        return result

    output = translate_block(item, aligner, policy, pair)
    hybrid = output.report.hybrid
    if hybrid.spanwise:
        result.update(status="fallback", fallback_reason=", ".join(sorted(hybrid.spanwise)))
        return result
    if hybrid.blocks == 0:
        result["status"] = "not_hybrid"
        return result

    block = without_namespaces(item_block(output.tree))
    hypothesis = inner_xml(block)
    fields = score(gold_fragment(item["gold"], etree.QName(block).localname), hypothesis)
    result.update(output=hypothesis, placements=dict(hybrid.placements), score=fields)
    result["status"] = "scored" if fields["same_text"] else "text_differs"
    return result


# ---------------------------------------------------------------------------
# Many items, several aligners
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


def summarise(results):
    """Summary of one aligner's results: statuses, fallback rate and reasons, scores overall and per text type."""
    statuses = Counter(result["status"] for result in results)
    scored = [result for result in results if result["status"] == "scored"]
    by_type = {}
    for result in scored:
        by_type.setdefault(result.get("type") or "unknown", []).append(result)
    reasons = Counter()
    for result in results:
        if result["status"] == "fallback":
            for reason in result["fallback_reason"].split(", "):
                reasons[reason] += 1
    summary = aggregate(scored)
    summary.update(
        items=len(results),
        statuses=dict(statuses),
        fallback_rate=statuses["fallback"] / len(results) if results else None,
        fallback_reasons=dict(reasons),
        by_type={text_type: aggregate(group) for text_type, group in sorted(by_type.items())},
    )
    return summary


def evaluate(items, aligners, policy=None, pair=None):
    """Run every item with every aligner.

    aligners: {name: aligner object} (e.g. from tei_translate.align.get_aligner).
    policy: defaults to load_policy() (fixed elements scored as wraps).
    pair: language-pair config, defaults to config/pairs/grc-en.yaml.
    Returns {aligner name: {"results": [...], "summary": {...}}}.
    """
    policy = policy or load_policy()
    pair = pair or load_pair()
    runs = {}
    for name, aligner in aligners.items():
        results = [run_item(item, aligner, policy, pair) for item in items]
        runs[name] = {"results": results, "summary": summarise(results)}
    return runs
