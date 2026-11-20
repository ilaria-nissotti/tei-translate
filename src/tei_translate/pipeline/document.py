"""Translate one TEI document: the library entry point used by the CLI (and later Gradio).

    from tei_translate.pipeline.document import translate_document
    result = translate_document("in.xml", engine="tag", placement="hybrid", aligner="monotone")
    result.tree.write("out.xml", encoding="UTF-8", xml_declaration=True)
    print(result.report.summary())
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from lxml import etree

from tei_translate.align import get_aligner
from tei_translate.engines import get_engine
from tei_translate.pipeline.hybrid import HybridReport, run_hybrid
from tei_translate.pipeline.policy import REPO_ROOT, Policy, local_name
from tei_translate.pipeline.spans import WalkReport, collect_spans, has_letters, split_ws, write_back
from tei_translate.pipeline.transliterate import get_transliterator
from tei_translate.pipeline.validate import validate

log = logging.getLogger(__name__)

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
DEFAULT_PAIR = REPO_ROOT / "config" / "pairs" / "grc-en.yaml"

# Supported values per rule parameter, default first; anything else gives a warning.
SUPPORTED_PARAMS = {
    "convert": ("none",),                            # keep (num): Arabic conversion not implemented yet
    "scheme": ("simple",),                           # transliterate
    # Hybrid placement (ignored in span-wise mode), see pipeline/placement.py:
    "placement": ("align", "boundary"),              # default: align for elements with text, boundary for points
    "fallback": ("spanwise", "boundary", "sentence"),
    "anchor": ("left", "right"),                     # points placed by alignment
    "mt_input": ("source", "remove"),                # fixed content: shown to the model or removed
}
# hybrid: whole sentences to the model, tags placed afterwards; spanwise: every text piece where it is.
PLACEMENTS = ("hybrid", "spanwise")


@dataclass
class Report:
    engine: str
    src: str
    tgt: str
    walk: WalkReport
    translated_spans: int = 0
    transliterated_spans: int = 0
    skipped_spans: int = 0     # no letters (numbers, punctuation)
    lang_updated: int = 0
    warnings: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)
    placement: str = "spanwise"
    aligner: str | None = None
    hybrid: HybridReport = field(default_factory=HybridReport)

    @property
    def ok(self) -> bool:
        return all(c["ok"] for c in self.checks.values())

    def summary(self) -> str:
        lines = [
            f"engine: {self.engine} ({self.src} -> {self.tgt})",
            f"spans: {self.translated_spans} translated, {self.transliterated_spans} transliterated, "
            f"{self.skipped_spans} skipped (no letters)",
            f"xml:lang updated on {self.lang_updated} elements",
        ]
        if self.placement == "hybrid":
            h = self.hybrid
            lines.append(f"placement: hybrid, aligner: {self.aligner}; {h.blocks} blocks placed "
                         f"({h.sentences} sentences translated, {h.aligned_sentences} aligned), "
                         f"{sum(h.spanwise.values())} blocks span-wise")
            if h.placements:
                lines.append("  tags placed: " + ", ".join(f"{k} ({v})" for k, v in sorted(h.placements.items())))
            if h.spanwise:
                lines.append("  span-wise because: " + ", ".join(
                    f"{k} ({v})" for k, v in h.spanwise.most_common()))
        else:
            lines.append("placement: spanwise")
        lines.append("rules fired:")
        lines += [f"  {rule_id}: {n}" for rule_id, n in sorted(self.walk.rules_fired.items())]
        if self.walk.unknown_tags:
            lines.append("unknown tags (default rule): " + ", ".join(
                f"{t} ({n})" for t, n in sorted(self.walk.unknown_tags.items())))
        if self.walk.cases:
            lines.append("special cases: " + ", ".join(f"{c} ({n})" for c, n in sorted(self.walk.cases.items())))
        for w in self.walk.warnings + self.warnings:
            lines.append(f"WARNING: {w}")
        lines.append("validation:")
        for name, c in self.checks.items():
            status = "PASS" if c["ok"] else "FAIL"
            detail = f" ({c['detail']})" if c.get("detail") else ""
            lines.append(f"  {status} {name}{detail}")
        return "\n".join(lines)


@dataclass
class Result:
    tree: object
    report: Report


def load_pair(path: str | Path = DEFAULT_PAIR) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def text_elements(root) -> list:
    """Outermost <text> elements (a <group> may nest further <text>s inside them)."""
    return root.xpath("//*[local-name()='text'][not(ancestor::*[local-name()='text'])]")


def _check_params(policy: Policy) -> list[str]:
    warnings = []
    rules = [policy.default, policy.empty, *policy.tags.values(), *(r for _, _, r in policy.overrides)]
    for rule in rules:
        for key, value in rule.params.items():
            if key not in SUPPORTED_PARAMS:
                warnings.append(f"{rule.rule_id}: unknown parameter {key!r} ignored")
            elif value not in SUPPORTED_PARAMS[key]:
                warnings.append(f"{rule.rule_id}: {key}={value!r} not supported, using the default")
    return warnings


def _update_lang(text_elem, policy: Policy, src: str, tgt: str) -> int:
    """Set xml:lang=src -> tgt on elements whose text was translated (not inside kept elements)."""
    count = 0

    def visit(elem, kept):
        nonlocal count
        if not isinstance(elem.tag, str):
            return
        rule = policy.classify(elem)
        kept = kept or rule.treatment in ("keep", "keep-subtree") or local_name(elem) in policy.untouched
        if not kept and elem.get(XML_LANG) == src:
            elem.set(XML_LANG, tgt)
            count += 1
        for child in elem:
            visit(child, kept)

    visit(text_elem, False)
    return count


def _add_resp_stmt(root, engine_name: str, src: str, tgt: str) -> bool:
    found = root.xpath("//*[local-name()='teiHeader']/*[local-name()='fileDesc']/*[local-name()='titleStmt']")
    if not found:
        return False
    title_stmt = found[0]
    ns = etree.QName(title_stmt).namespace
    q = (lambda t: f"{{{ns}}}{t}") if ns else (lambda t: t)
    resp_stmt = etree.SubElement(title_stmt, q("respStmt"))
    resp = etree.SubElement(resp_stmt, q("resp"))
    resp.text = f"machine translation ({src} to {tgt}), engine: {engine_name}"
    name = etree.SubElement(resp_stmt, q("name"))
    name.text = "tei-translate"
    # Match the indentation of the previous sibling, if any.
    prev = resp_stmt.getprevious()
    if prev is not None:
        resp_stmt.tail = prev.tail  # the closing indentation of titleStmt
        before = prev.getprevious()
        prev.tail = before.tail if before is not None else title_stmt.text
    return True


def apply_spans(spans, engine, src: str, tgt: str, report: Report) -> None:
    """Transliterate and translate spans in place (one batch to the engine); counts go to `report`.

    The spans may come from several trees, e.g. many passages translated in one batch.
    """
    to_translate = []
    for span in spans:
        core = split_ws(span.value)[1]
        if not has_letters(core):
            report.skipped_spans += 1
        elif span.treatment == "translate":
            to_translate.append((span, core))
        else:
            scheme = span.params.get("scheme", "simple")
            if scheme not in SUPPORTED_PARAMS["scheme"]:
                scheme = SUPPORTED_PARAMS["scheme"][0]
            write_back(span, get_transliterator(src, scheme)(core))
            report.transliterated_spans += 1

    outputs = engine.translate([core for _, core in to_translate], src, tgt) if to_translate else []
    if len(outputs) != len(to_translate):
        raise RuntimeError(f"engine {engine.name} returned {len(outputs)} segments for {len(to_translate)}")
    for (span, _), out in zip(to_translate, outputs):
        write_back(span, out)
    report.translated_spans += len(to_translate)


def translate_document(path, pair: str | Path | dict = DEFAULT_PAIR, engine=None, policy: Policy | None = None,
                       placement: str | None = None, aligner=None) -> Result:
    """Translate a TEI file. `engine` and `aligner` (name or object) and `placement`
    (hybrid | spanwise) override the pair config."""
    pair_cfg = pair if isinstance(pair, dict) else load_pair(pair)
    src, tgt = pair_cfg["src"], pair_cfg["tgt"]
    placement = placement or pair_cfg.get("placement", "hybrid")
    if placement not in PLACEMENTS:
        raise ValueError(f"unknown placement {placement!r}; use one of {', '.join(PLACEMENTS)}")
    if policy is None:
        policy = Policy.load(REPO_ROOT / pair_cfg.get("policy", "config/policy.yaml"))
    engine = engine or pair_cfg.get("engine", "identity")
    if isinstance(engine, str):
        engine = get_engine(engine)

    parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(str(path), parser)
    source = copy.deepcopy(tree)
    root = tree.getroot()

    texts = text_elements(root)
    if not texts:
        raise ValueError(f"{path}: no <text> element found")

    spans, walk = [], WalkReport()
    for text_elem in texts:
        s, w = collect_spans(text_elem, policy)
        spans += s
        walk.rules_fired.update(w.rules_fired)
        walk.unknown_tags.update(w.unknown_tags)
        walk.cases.update(w.cases)
        walk.warnings += w.warnings
    for tag, n in walk.unknown_tags.items():
        log.warning("unknown tag <%s> (%d times): default rule used", tag, n)

    report = Report(engine.name, src, tgt, walk, warnings=_check_params(policy), placement=placement)
    if placement == "hybrid":
        aligner = aligner or pair_cfg.get("aligner", "none")
        if isinstance(aligner, str):
            aligner = get_aligner(aligner)
        report.aligner = aligner.name
        spans = run_hybrid(spans, policy, engine, aligner, src, tgt, report.hybrid)
    apply_spans(spans, engine, src, tgt, report)

    for text_elem in texts:
        report.lang_updated += _update_lang(text_elem, policy, src, tgt)
    if not _add_resp_stmt(root, engine.name, src, tgt):
        report.warnings.append("no teiHeader/fileDesc/titleStmt: respStmt not added")

    report.checks = validate(source, tree, policy, src, tgt)
    return Result(tree, report)
