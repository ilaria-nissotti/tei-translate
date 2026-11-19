import pytest
from lxml import etree

from tei_translate.pipeline.policy import Policy

TEI = "http://www.tei-c.org/ns/1.0"


def tei(xml):
    """Parse a fragment whose root gets the TEI namespace."""
    root = etree.fromstring(f'<wrap xmlns="{TEI}">{xml}</wrap>')
    return root[0]


policy = Policy.load()


def test_block_and_container():
    assert policy.classify(tei("<p>x</p>")).role == "block"
    assert policy.classify(tei("<div><p>x</p></div>")).role == "container"


def test_tag_rule_with_params():
    rule = policy.classify(tei("<num>δʹ</num>"))
    assert (rule.role, rule.treatment, rule.rule_id) == ("inline", "keep", "tags.num")
    assert rule.params == {"convert": "none"}


def test_override_by_attribute():
    assert policy.classify(tei('<name type="person">Περικλῆς</name>')).treatment == "transliterate"
    rule = policy.classify(tei('<name type="ethnic">Ἀθηναίοις</name>'))
    assert (rule.treatment, rule.rule_id) == ("translate", "overrides[0]")


def test_empty_detected_not_listed():
    for xml in ['<pb n="1"/>', '<milestone unit="para"/>', '<gap/>', '<somethingNew/>']:
        rule = policy.classify(tei(xml))
        assert (rule.role, rule.rule_id) == ("empty", "empty"), xml


def test_tag_entry_wins_over_empty():
    assert policy.classify(tei("<p/>")).role == "block"


def test_unknown_tag_uses_default_and_warns():
    rule = policy.classify(tei("<unknownTag>x</unknownTag>"))
    assert (rule.rule_id, rule.treatment, rule.warn) == ("default", "translate", True)


def test_note_is_keep_subtree():
    assert policy.classify(tei("<note>coni. Apelt</note>")).treatment == "keep-subtree"


def test_bad_policy_rejected():
    with pytest.raises(ValueError):
        Policy({"tags": {"p": {"role": "block", "treatment": "paraphrase"}}})
    with pytest.raises(ValueError):
        Policy({"tags": {"p": {"role": "block"}}})
