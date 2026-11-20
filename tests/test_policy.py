import pytest
from lxml import etree

from tei_translate.pipeline.policy import Policy

TEI = "http://www.tei-c.org/ns/1.0"


def tei(xml):
    """Parse a fragment whose root gets the TEI namespace."""
    root = etree.fromstring(f'<wrap xmlns="{TEI}">{xml}</wrap>')
    return root[0]


policy = Policy.load()


def test_live_policy_translates_names_and_numbers():
    for xml in ['<num>δʹ</num>', '<name type="person">Περικλῆς</name>', '<name type="ethnic">Ἀθηναίοις</name>',
                '<persName>Σωκράτης</persName>', '<placeName>Ἀθῆναι</placeName>', '<rs type="nomorph">Ἴων</rs>']:
        assert policy.classify(tei(xml)).treatment == "translate", xml
    assert policy.classify(tei("<label>ΜΟΣΧΙΩΝ.</label>")).treatment == "transliterate"


def test_block_and_container():
    assert policy.classify(tei("<p>x</p>")).role == "block"
    assert policy.classify(tei("<div><p>x</p></div>")).role == "container"


def test_tag_rule_with_params():
    rule = policy.classify(tei("<label>ΣΩ.</label>"))
    assert (rule.role, rule.treatment, rule.rule_id) == ("inline", "transliterate", "tags.label")
    assert rule.params == {"scheme": "simple"}


def test_keep_rules():
    for xml in ["<term>Μ</term>", '<foreign xml:lang="lat">ita</foreign>', "<bibl>Hom. Il. 2.108</bibl>"]:
        assert policy.classify(tei(xml)).treatment == "keep", xml


def test_override_by_attribute():
    rule = policy.classify(tei('<milestone unit="para" n="2"/>'))
    assert (rule.rule_id, rule.params) == ("overrides[0]", {"placement": "boundary"})
    assert policy.classify(tei('<milestone unit="section" n="2"/>')).rule_id == "tags.milestone"


def test_empty_detected_not_listed():
    for xml in ['<pb n="1"/>', '<lb/>', '<somethingNew/>']:
        rule = policy.classify(tei(xml))
        assert (rule.role, rule.rule_id) == ("empty", "empty"), xml
        assert rule.params == {"placement": "boundary"}


def test_listed_empty_markers_follow_the_words():
    milestone = policy.classify(tei('<milestone unit="section" n="2"/>'))
    assert (milestone.role, milestone.rule_id) == ("empty", "tags.milestone")
    assert milestone.params["placement"] == "align" and milestone.params["anchor"] == "right"
    para = policy.classify(tei('<milestone unit="para"/>'))
    assert (para.role, para.rule_id, para.params) == ("empty", "overrides[0]", {"placement": "boundary"})
    assert policy.classify(tei("<gap/>")).params["anchor"] == "left"


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
