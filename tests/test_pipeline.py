from pathlib import Path

import pytest
from lxml import etree

from tei_translate.pipeline.document import translate_document
from tei_translate.pipeline.transliterate import grc_simple

FIXTURES = Path(__file__).parent / "fixtures" / "tei"
ALL = sorted(FIXTURES.glob("*.xml"))
HANDMADE = FIXTURES / "handmade.xml"
NS = {"t": "http://www.tei-c.org/ns/1.0"}
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def find(tree, xpath):
    return tree.xpath(xpath, namespaces=NS)


@pytest.mark.parametrize("path", ALL, ids=[p.name for p in ALL])
@pytest.mark.parametrize("engine", ["identity", "tag"])
def test_all_checks_pass(path, engine):
    result = translate_document(path, engine=engine, placement="spanwise")
    failed = {k: v for k, v in result.report.checks.items() if not v["ok"]}
    assert not failed, result.report.summary()


@pytest.mark.parametrize("path", ALL, ids=[p.name for p in ALL])
def test_identity_roundtrip_keeps_translated_text(path):
    """With the identity engine only names (transliterated), xml:lang and the respStmt change."""
    source = etree.parse(str(path))
    result = translate_document(path, engine="identity", placement="spanwise")
    src_text = find(source, "//t:text")[0]
    out_text = find(result.tree, "//t:text")[0]
    src_nodes = [e for e in src_text.iter() if isinstance(e.tag, str)]
    out_nodes = [e for e in out_text.iter() if isinstance(e.tag, str)]
    assert len(src_nodes) == len(out_nodes)
    for a, b in zip(src_nodes, out_nodes):
        if etree.QName(a).localname in ("name", "persName", "placeName", "rs", "label", "speaker"):
            continue
        assert (a.text, a.tail) == (b.text, b.tail)


def tagged():
    return translate_document(HANDMADE, engine="tag", placement="spanwise").tree


def test_translated_spans_are_wrapped():
    tree = tagged()
    p = find(tree, "//t:text//t:p")[0]
    assert p.text == "[EN:ὁ] "
    assert find(tree, "//t:head")[0].text == "[EN:Περὶ τοῦ πολέμου]"
    assert find(tree, "//t:q")[0].text == "[EN:ἴωμεν]"
    assert find(tree, "//t:hi")[0].text == "[EN:ταχέως]"
    assert find(tree, "//t:unknownTag")[0].text == "[EN:ἄγνωστον]"


def test_keep_and_note_unchanged_and_in_place():
    tree = tagged()
    p = find(tree, "//t:text//t:p")[0]
    assert find(tree, "//t:num")[0].text == "δʹ"
    assert find(tree, "//t:bibl")[0].text == "Hom. Il. 2.108"
    note = find(tree, "//t:note")[0]
    assert etree.tostring(note, encoding="unicode", with_tail=False).endswith(
        'coni. <foreign xml:lang="grc">Ἀπελτ</foreign> Apelt</note>')
    # The note stays between λόγους and τοῖς, and the text after it is translated.
    assert tree.getpath(note.getparent()) == tree.getpath(p)
    assert note.getprevious().tail == " [EN:λόγους]"
    assert note.tail == " [EN:τοῖς] "


def test_names():
    tree = tagged()
    assert find(tree, "//t:name[@type='person']")[0].text == "Perikles"
    assert find(tree, "//t:name[@type='ethnic']")[0].text == "[EN:Ἀθηναίοις]"
    speaker = find(tree, "//t:speaker")[0]
    assert speaker.text == "Sokrates "
    assert find(tree, "//t:speaker/t:num")[0].text == "α"  # keep wins inside a transliterated speaker


def test_markers_comments_and_tails():
    tree = tagged()
    assert find(tree, "//t:milestone")[0].tail == " [EN:καὶ ἀπῆλθεν.]"
    assert find(tree, "//t:pb")[0].tail == "[EN:ἔφη δὲ] "
    assert find(tree, "//t:lb")[0].tail == "[EN:φής;] "
    comment = find(tree, "//t:p[@xml:id='p2']/comment()")[0]
    assert comment.tail == " [EN:οὐδὲν] "
    assert find(tree, "//t:gap")[0].tail == " [EN:λέγεις.]"


def test_block_inside_inline():
    tree = tagged()
    assert find(tree, "//t:l")[0].text == "[EN:μῆνιν ἄειδε θεὰ]"
    assert find(tree, "//t:quote")[0].tail == " [EN:ὁ ποιητής.]"


def test_report_and_header():
    result = translate_document(HANDMADE, engine="tag", placement="spanwise")
    report = result.report
    assert report.walk.unknown_tags["unknownTag"] == 1
    assert report.walk.rules_fired["overrides[0]"] == 1
    assert report.walk.cases["block-in-block"] == 1  # <l> inside <quote> inside <p>
    tree = result.tree
    assert find(tree, "//t:text")[0].get(XML_LANG) == "en"
    assert find(tree, "//t:div[@type='edition']")[0].get(XML_LANG) == "en"
    assert find(tree, "//t:note")[0].get(XML_LANG) == "lat"
    assert find(tree, "//t:foreign")[0].get(XML_LANG) == "grc"
    resp = find(tree, "//t:titleStmt/t:respStmt/t:resp")[0]
    assert "engine: tag" in resp.text


@pytest.mark.parametrize("greek, latin", [
    ("Περικλῆς", "Perikles"),
    ("Σωκράτης", "Sokrates"),
    ("Ἡρόδοτος", "Herodotos"),
    ("Ῥόδος", "Rhodos"),
    ("Ἀγγελος", "Angelos"),
    ("Οἱ", "Hoi"),
    ("Ζεύς", "Zeus"),
])
def test_transliteration(greek, latin):
    assert grc_simple(greek) == latin
