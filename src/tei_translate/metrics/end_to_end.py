"""End-to-end evaluation (question 3): translation and tags together, on the gold set.

Questions 1 and 2 test the parts separately: translation quality on plain text
(metrics.translation_eval) and tag placement given a translation
(metrics.placement_eval). This module runs the real pipeline, with a real MT
engine and aligner, on the Greek source files of the gold set
(data/gold/grc-en/) and compares its English TEI with the gold English TEI,
which has the same tags placed by hand.

Conditions (the same engine translates the same Greek in each):
- "hybrid":   the pipeline's default: whole sentences translated, tags put
              back with the aligner (blocks it cannot place go span-wise);
- "spanwise": every text piece between tags translated on its own (tags
              never move);
- "plain":    the text of each block without any tags, translated as one
              segment. No tags, so no structure scores: the upper bound for
              translation quality, i.e. what handling the tags costs.

Unit of scoring: the text block (paragraph, verse line, ...). Greek, gold
and output blocks are paired by position (all three have the same
structure). Only blocks the hybrid pipeline handles are scored (treatment
translate, no blocks inside them), and only where the gold block is
translated (partial gold files leave some blocks in Greek). Every condition
is scored on the same blocks. Notes and references count as points (their
content is copied unchanged by the pipeline and is left out on all sides),
and xml:lang attributes are ignored (the validator checks them).

Scores per condition:
- validator: share of files that pass every check of pipeline/validate.py;
- structure match: share of blocks with exactly the gold's tags (same
  elements, attributes and nesting; order ignored): metrics.scores.same_structure;
- chrF, BLEU (and COMET if asked) on the text without tags, against the gold;
- Node-chrF: chrF inside each element, elements paired by tag and attributes
  (metrics.translation_scores.node_chrf): are the right words in the right tags?
- hybrid only: how many blocks were placed and how many went span-wise, and why.
"""

import copy
import re
import time
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

from lxml import etree

from tei_translate.metrics.comet_score import DEFAULT_MODEL, comet_scores
from tei_translate.metrics.placement_eval import (
    empty_points, inner_xml, is_scorable, citation, text_blocks, without_namespaces,
)
from tei_translate.metrics.scores import same_structure, xml_accuracy
from tei_translate.metrics.translation_scores import bleu, chrf, node_chrf
from tei_translate.pipeline.detag import detag
from tei_translate.pipeline.document import translate_document

CONDITIONS = ("plain", "hybrid", "spanwise")
TAGGED = ("hybrid", "spanwise")
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
GREEK_LETTER = re.compile(r"[Ͱ-Ͽἀ-῿]")
LETTER = re.compile(r"[^\W\d_]")


class StructureMismatch(ValueError):
    """The Greek file and its gold file do not have the same number of text blocks."""


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

def without_lang(elem):
    """Remove xml:lang from elem and everything below it (changes it in place). Returns elem."""
    for child in elem.iter():
        if isinstance(child.tag, str) and XML_LANG in child.attrib:
            del child.attrib[XML_LANG]
    return elem


def block_fragment(block, policy):
    """The content of a block as an XML fragment, for scoring: no namespace, no xml:lang,
    notes and references emptied (single points). The block itself is not changed."""
    return inner_xml(empty_points(without_lang(without_namespaces(block)), policy))


def block_text(block, policy):
    """The plain text of a block as the pipeline sends it to the engine (notes and references left out)."""
    return detag(copy.deepcopy(block), policy).text


def is_untranslated(text):
    """True if most letters of text are Greek: a gold block left in Greek (a partial gold file).

    A translated block may still contain some Greek (a kept <foreign> word),
    so a few Greek letters are allowed.
    """
    letters = LETTER.findall(text)
    if not letters:
        return False
    greek = sum(1 for letter in letters if GREEK_LETTER.match(letter))
    return greek > len(letters) / 2


def select_units(greek_tree, gold_tree, policy, max_blocks=None):
    """The blocks to score in one file: one dict per block (index, citation, source, reference, greek_text).

    index is the block's position among all text blocks (the same in the
    Greek, gold and output files). max_blocks: only blocks among the first
    max_blocks are used. Raises StructureMismatch if the files do not have
    the same number of blocks.
    """
    greek_blocks, gold_blocks = text_blocks(greek_tree, policy), text_blocks(gold_tree, policy)
    if len(greek_blocks) != len(gold_blocks):
        raise StructureMismatch(f"{len(greek_blocks)} Greek blocks but {len(gold_blocks)} gold blocks")
    units = []
    for index, (greek_block, gold_block) in enumerate(zip(greek_blocks, gold_blocks)):
        if max_blocks is not None and index >= max_blocks:
            break
        if not is_scorable(greek_block, policy):
            continue
        greek_text, english_text = block_text(greek_block, policy), block_text(gold_block, policy)
        if not LETTER.search(greek_text) or not english_text.strip() or is_untranslated(english_text):
            continue
        units.append({"index": index, "citation": citation(greek_block), "greek_text": greek_text,
                      "source": block_fragment(greek_block, policy),
                      "reference": block_fragment(gold_block, policy)})
    return units


def truncate(tree, policy, max_blocks):
    """Remove every text block after the first max_blocks (changes tree in place). Returns tree.

    Used to translate only the beginning of a long file. The blocks that stay
    keep their positions, so they still pair with the gold blocks.
    """
    for block in text_blocks(tree, policy)[max_blocks:]:
        parent = block.getparent()
        if parent is not None:
            parent.remove(block)
    return tree


# ---------------------------------------------------------------------------
# Running the conditions
# ---------------------------------------------------------------------------

def translate_plain(units, engine, src, tgt):
    """Translate each unit's text without tags, one segment per block. Returns XML-safe strings."""
    translations = engine.translate([unit["greek_text"] for unit in units], src, tgt)
    return [escape(text) for text in translations]


def hybrid_counts(report):
    """The hybrid part of a pipeline report as plain numbers."""
    return {"blocks_placed": report.hybrid.blocks,
            "blocks_spanwise": sum(report.hybrid.spanwise.values()),
            "spanwise_reasons": dict(report.hybrid.spanwise)}


def run_tagged(source_path, units, condition, engine, aligner, policy, pair, out_path=None):
    """Run the pipeline in one placement mode. Returns the condition's result for this file.

    out_path: if given, the English TEI file is written there.
    """
    result = translate_document(source_path, pair, engine=engine, policy=policy, placement=condition,
                                aligner=aligner)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result.tree.write(str(out_path), encoding="UTF-8", xml_declaration=True)
    blocks = text_blocks(result.tree, policy)
    checks = {name: check["ok"] for name, check in result.report.checks.items()}
    entry = {"hyps": [block_fragment(blocks[unit["index"]], policy) for unit in units], "checks": checks}
    if condition == "hybrid":
        entry["hybrid"] = hybrid_counts(result.report)
    return entry


def evaluate_file(entry, engine, aligner, policy, pair, conditions=("hybrid", "spanwise"),
                  max_blocks=None, out_dir=None):
    """Run every condition on one gold file's Greek source.

    entry: one item of metrics.placement_eval.load_index(). out_dir: if given,
    the (truncated) Greek input and each condition's English TEI are written
    there. Returns {"gold_file", "units", "conditions": {condition: {"hyps",
    "checks", "seconds", ["hybrid"]}}}, or {"gold_file", "error"} if the
    files do not have the same structure.
    """
    parser = etree.XMLParser(remove_blank_text=False)
    greek_tree = etree.parse(str(entry["greek_path"]), parser)
    gold_tree = etree.parse(str(entry["gold_path"]), parser)
    try:
        units = select_units(greek_tree, gold_tree, policy, max_blocks)
    except StructureMismatch as error:
        return {"gold_file": entry["gold_file"], "error": str(error)}
    name = Path(entry["greek_path"]).name
    source_path = Path(entry["greek_path"])
    if max_blocks is not None:
        if out_dir is None:
            raise ValueError("max_blocks needs out_dir (the truncated Greek file is written there)")
        source_path = Path(out_dir) / "greek" / name
        source_path.parent.mkdir(parents=True, exist_ok=True)
        truncate(greek_tree, policy, max_blocks).write(str(source_path), encoding="UTF-8", xml_declaration=True)
    results = {}
    for condition in conditions:
        start = time.time()
        if condition == "plain":
            results[condition] = {"hyps": translate_plain(units, engine, pair["src"], pair["tgt"]), "checks": None}
        else:
            out_path = Path(out_dir) / condition / name.replace(".xml", ".en.xml") if out_dir else None
            results[condition] = run_tagged(source_path, units, condition, engine, aligner, policy, pair, out_path)
        results[condition]["seconds"] = round(time.time() - start, 1)
    return {"gold_file": entry["gold_file"], "units": units, "conditions": results}


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------

def mean(values):
    """The average of a list (None values left out), or None if nothing is left."""
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def text_scores(references, hypotheses, passage_comet=None):
    """chrF, BLEU and (if given) the average COMET of a set of blocks."""
    return {
        "blocks": len(hypotheses),
        "chrf": chrf(references, hypotheses) if hypotheses else None,
        "bleu": bleu(references, hypotheses) if hypotheses else None,
        "comet": mean(passage_comet) if passage_comet is not None else None,
    }


def tag_scores(references, hypotheses):
    """Node-chrF, structure match and XML accuracy of tagged output blocks against the gold blocks."""
    node = [node_chrf(reference, hypothesis) for reference, hypothesis in zip(references, hypotheses)]
    same = [same_structure(reference, hypothesis) for reference, hypothesis in zip(references, hypotheses)]
    return {"node_chrf": mean(node), "structure_match": mean([1.0 if s else 0.0 for s in same]),
            "xml_accuracy": xml_accuracy(hypotheses)}


def summarise(file_results, condition, use_comet=False, comet_model=DEFAULT_MODEL, batch_size=8, scorer=None):
    """All scores of one condition over every file (blocks pooled), plus per file.

    Returns a dict with the text scores (chrf, bleu, comet), for tagged
    conditions node_chrf, structure_match, xml_accuracy and the validator
    results, for hybrid the placement counts, and "per_file". Also returns
    the per-block COMET scores under "block_comet" (None without COMET).
    """
    done = [result for result in file_results if "units" in result and condition in result["conditions"]]
    sources = [unit["source"] for result in done for unit in result["units"]]
    references = [unit["reference"] for result in done for unit in result["units"]]
    hypotheses = [hyp for result in done for hyp in result["conditions"][condition]["hyps"]]
    block_comet = comet_scores(sources, references, hypotheses, comet_model, batch_size, scorer) \
        if use_comet and hypotheses else None
    summary = text_scores(references, hypotheses, block_comet)
    summary["block_comet"] = block_comet
    summary["seconds"] = round(sum(result["conditions"][condition]["seconds"] for result in done), 1)
    if condition in TAGGED:
        summary.update(tag_scores(references, hypotheses))
        failed = Counter(name for result in done
                         for name, ok in result["conditions"][condition]["checks"].items() if not ok)
        passed = sum(1 for result in done if all(result["conditions"][condition]["checks"].values()))
        summary.update(files=len(done), files_valid=passed, failed_checks=dict(failed))
    if condition == "hybrid":
        reasons = Counter()
        for result in done:
            reasons.update(result["conditions"]["hybrid"]["hybrid"]["spanwise_reasons"])
        summary.update(
            blocks_placed=sum(result["conditions"]["hybrid"]["hybrid"]["blocks_placed"] for result in done),
            blocks_spanwise=sum(result["conditions"]["hybrid"]["hybrid"]["blocks_spanwise"] for result in done),
            spanwise_reasons=dict(reasons))
    summary["per_file"] = {}
    position = 0
    for result in done:
        count = len(result["units"])
        refs = references[position:position + count]
        hyps = hypotheses[position:position + count]
        comet_part = block_comet[position:position + count] if block_comet is not None else None
        part = text_scores(refs, hyps, comet_part)
        if condition in TAGGED and hyps:
            part.update(tag_scores(refs, hyps))
        summary["per_file"][result["gold_file"]] = part
        position += count
    return summary
