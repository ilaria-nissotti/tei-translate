"""Collect the text pieces (spans) of a TEI <text> element and write results back.

Span-wise translation: every piece of text is handled where it is, so no
element ever moves. In lxml, `elem.text` is the text before the first child
and `child.tail` is the text after the child's end tag, which belongs to the
parent. So:

- `elem.text` gets the treatment of `elem`;
- `child.tail` gets the treatment of the parent.

Text outside blocks is never touched. For nested inline elements the more
protective treatment wins (keep > transliterate > translate): everything inside
a kept element is kept, and a <num> inside a transliterated label stays kept.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from lxml import etree

from tei_translate.pipeline.policy import Policy, Rule, local_name

# Treatments that produce new text; `keep` spans are never collected.
CHANGING = {"translate", "transliterate"}
# Nested inline elements: the more protective treatment wins (keep > transliterate > translate).
PROTECTION = {"translate": 0, "transliterate": 1, "keep": 2}


@dataclass
class Span:
    elem: object            # lxml element that owns the text
    slot: str               # "text" or "tail"
    treatment: str          # "translate" or "transliterate"
    rule_id: str
    params: dict

    @property
    def value(self) -> str:
        return (self.elem.text if self.slot == "text" else self.elem.tail) or ""


@dataclass
class WalkReport:
    rules_fired: Counter = field(default_factory=Counter)   # rule_id -> number of elements
    unknown_tags: Counter = field(default_factory=Counter)  # tag -> count (default rule)
    cases: Counter = field(default_factory=Counter)         # structural special cases
    warnings: list = field(default_factory=list)


def is_element(node) -> bool:
    """False for comments and processing instructions (their tail still counts)."""
    return isinstance(node.tag, str)


def _has_own_text(elem) -> bool:
    if (elem.text or "").strip():
        return True
    return any((child.tail or "").strip() for child in elem)


def _has_block_child(elem, policy: Policy) -> bool:
    return any(is_element(c) and policy.classify(c).role == "block" for c in elem)


def collect_spans(text_elem, policy: Policy) -> tuple[list[Span], WalkReport]:
    """Walk a TEI <text> element and return the spans to translate or transliterate."""
    spans: list[Span] = []
    report = WalkReport()

    def emit(node, slot, ctx):
        if ctx is None or ctx[0] not in CHANGING:
            return
        value = (node.text if slot == "text" else node.tail) or ""
        if value.strip():
            treatment, rule_id, params = ctx
            spans.append(Span(node, slot, treatment, rule_id, params))

    def visit(elem, parent_ctx):
        """parent_ctx: (treatment, rule_id, params) of the enclosing text, or None outside blocks."""
        name = local_name(elem)
        if name in policy.untouched:
            report.rules_fired["untouched"] += 1
            return
        rule: Rule = policy.classify(elem)
        report.rules_fired[rule.rule_id] += 1
        if rule.warn:
            report.unknown_tags[name] += 1

        if rule.treatment == "keep-subtree":
            return  # copied unchanged; its tail is handled by the parent

        in_block = parent_ctx is not None
        own_ctx = (rule.treatment, rule.rule_id, rule.params)

        if rule.role == "empty":
            return
        if rule.role == "container":
            own_ctx = parent_ctx
            if not in_block and _has_own_text(elem):
                report.cases["text-in-container"] += 1
                report.warnings.append(f"<{name}> is a container but holds text outside any block; left unchanged")
        elif rule.role == "block":
            if in_block:
                report.cases["block-in-block"] += 1
        elif rule.role == "inline":
            if not in_block:
                if _has_own_text(elem):
                    report.cases["inline-as-block"] += 1
                else:
                    if _has_block_child(elem, policy):
                        report.cases["inline-as-container"] += 1
                    own_ctx = None
            elif PROTECTION.get(parent_ctx[0], 0) > PROTECTION.get(rule.treatment, 0):
                own_ctx = parent_ctx  # the more protective treatment wins (a kept span keeps everything)
            elif _has_block_child(elem, policy):
                report.cases["inline-with-blocks"] += 1

        emit(elem, "text", own_ctx)
        for child in elem:
            if is_element(child):
                visit(child, own_ctx)
            emit(child, "tail", own_ctx)

    visit(text_elem, None)
    return spans, report


def split_ws(value: str) -> tuple[str, str, str]:
    """('  abc \\n') -> ('  ', 'abc', ' \\n')."""
    core = value.strip()
    if not core:
        return value, "", ""
    start = value.index(core)
    return value[:start], core, value[start + len(core):]


def has_letters(value: str) -> bool:
    return any(ch.isalpha() for ch in value)


def write_back(span: Span, new_core: str) -> None:
    """Replace the span's text, keeping its leading and trailing whitespace."""
    lead, _, trail = split_ws(span.value)
    new = lead + new_core + trail
    if span.slot == "text":
        span.elem.text = new
    else:
        span.elem.tail = new
