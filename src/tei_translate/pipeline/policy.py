"""Tag policy: decides the role and treatment of every TEI element.

All tag decisions live in a YAML file (config/policy.yaml); this module only
knows the roles and treatments. Lookup order for an element:
overrides (first match) -> tags -> empty -> default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from lxml import etree

ROLES = {"block", "container", "inline", "empty"}
TREATMENTS = {"translate", "keep", "transliterate", "keep-subtree", None}

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY = REPO_ROOT / "config" / "policy.yaml"


@dataclass(frozen=True)
class Rule:
    role: str
    treatment: str | None
    rule_id: str
    params: dict = field(default_factory=dict)
    warn: bool = False


def local_name(elem) -> str:
    """Tag name without namespace ('{http://www.tei-c.org/ns/1.0}p' -> 'p')."""
    return etree.QName(elem).localname


def is_empty(elem) -> bool:
    """No child elements and no text (whitespace does not count)."""
    return len(elem) == 0 and not (elem.text or "").strip()


def _attr(elem, name: str):
    """Attribute value by local name, so 'xml:lang' / 'type' work without namespaces."""
    if name.startswith("xml:"):
        name = "{http://www.w3.org/XML/1998/namespace}" + name[4:]
    return elem.get(name)


def _make_rule(spec: dict, rule_id: str) -> Rule:
    role = spec.get("role", "inline")
    treatment = spec.get("treatment")
    if role not in ROLES:
        raise ValueError(f"{rule_id}: unknown role {role!r}")
    if treatment not in TREATMENTS:
        raise ValueError(f"{rule_id}: unknown treatment {treatment!r}")
    if role in ("block", "inline") and treatment is None:
        raise ValueError(f"{rule_id}: role {role!r} needs a treatment")
    return Rule(role, treatment, rule_id, dict(spec.get("params") or {}), bool(spec.get("warn", False)))


class Policy:
    def __init__(self, data: dict):
        self.default = _make_rule(data.get("default", {"role": "inline", "treatment": "translate"}), "default")
        self.empty = _make_rule({"role": "empty", **data.get("empty", {"treatment": "keep"})}, "empty")
        self.untouched = set(data.get("untouched", []))
        self.tags = {name: _make_rule(spec, f"tags.{name}") for name, spec in (data.get("tags") or {}).items()}
        self.overrides = []
        for i, spec in enumerate(data.get("overrides") or []):
            rule = _make_rule(spec, f"overrides[{i}]")
            self.overrides.append((spec["tag"], dict(spec.get("attr") or {}), rule))

    @classmethod
    def load(cls, path: str | Path = DEFAULT_POLICY) -> "Policy":
        with open(path, encoding="utf-8") as f:
            return cls(yaml.safe_load(f) or {})

    def classify(self, elem) -> Rule:
        name = local_name(elem)
        for tag, attrs, rule in self.overrides:
            if tag == name and all(_attr(elem, k) == v for k, v in attrs.items()):
                return rule
        if name in self.tags:
            return self.tags[name]
        if is_empty(elem):
            return self.empty
        return self.default
