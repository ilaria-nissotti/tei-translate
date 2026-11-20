"""Hybrid placement: tags removed, whole sentences translated, tags put back.

Runs without models: the identity engine with the monotone aligner (exact
links), a word-reversing engine with an exact-match aligner (reordering), and
hand-made links for single blocks.
"""

from pathlib import Path

import pytest
from lxml import etree

from tei_translate.pipeline.detag import detag
from tei_translate.pipeline.document import translate_document
from tei_translate.pipeline.placement import Fallback, Layout, place, rebuild
from tei_translate.pipeline.policy import Policy
from tei_translate.pipeline.sentences import split_sentences

FIXTURES = Path(__file__).parent / "fixtures" / "tei"
ALL = sorted(FIXTURES.glob("*.xml"))
HANDMADE = FIXTURES / "handmade.xml"
TEI = "http://www.tei-c.org/ns/1.0"
NS = {"t": TEI}
policy = Policy.load()


class ReverseEngine:
    """Reverses the word order of every segment."""

    name = "reverse"

    def translate(self, segments, src, tgt):
        return [" ".join(reversed(s.split())) for s in segments]


class ExactAligner:
    """Links identical words (first unused match)."""

    name = "exact"

    def align(self, pairs):
        out = []
        for src, tgt in pairs:
            used, links = set(), set()
            for i, w in enumerate(src):
                j = next((j for j, v in enumerate(tgt) if v == w and j not in used), None)
                if j is not None:
                    used.add(j)
                    links.add((i, j))
            out.append(links)
        return out


def find(tree, xpath):
    return tree.xpath(xpath, namespaces=NS)


def inner(elem) -> str:
    """The element's content as XML, without its own tags and namespace declarations."""
    s = etree.tostring(elem, encoding="unicode", with_tail=False)
    s = s.replace(f' xmlns="{TEI}"', "")
    return s[s.index(">") + 1:s.rindex("</")]


# -- whole documents --------------------------------------------------------------

@pytest.mark.parametrize("path", ALL, ids=[p.name for p in ALL])
@pytest.mark.parametrize("engine, aligner", [("identity", "monotone"), ("identity", "none"), ("tag", "none"),
                                             (ReverseEngine(), ExactAligner())])
def test_all_checks_pass(path, engine, aligner):
    result = translate_document(path, engine=engine, placement="hybrid", aligner=aligner)
    failed = {k: v for k, v in result.report.checks.items() if not v["ok"]}
    assert not failed, result.report.summary()


def test_identity_tags_stay_on_their_words():
    result = translate_document(HANDMADE, engine="identity", placement="hybrid", aligner="monotone")
    tree = result.tree
    p1, p2 = find(tree, "//t:text//t:p")[:2]
    assert inner(p1) == (
        'ὁ <name type="person">Περικλῆς</name> εἶπε <num>δʹ</num> λόγους<note xml:lang="lat" n="n1">coni. '
        '<foreign xml:lang="grc">Ἀπελτ</foreign> Apelt</note> τοῖς <name type="ethnic">Ἀθηναίοις</name> '
        'καὶ ἀπῆλθεν.<milestone unit="para" n="2"/>')   # para milestone: boundary -> sentence end
    assert inner(p2) == ('<pb n="12"/>ἔφη δὲ <q>ἴωμεν</q> καὶ <bibl>Hom. Il. 2.108</bibl> '
                         '<unknownTag>ἄγνωστον</unknownTag> <hi rend="italic">ταχέως</hi>.')
    p3 = find(tree, "//t:p[@xml:id='p2']")[0]
    # lb: boundary (start of its sentence); comment between sentences stays there; gap follows οὐδὲν.
    assert inner(p3) == '<lb/>τί φής; <!-- a comment --> οὐδὲν <gap reason="lost"/> λέγεις.'
    # Fixed elements: the label is transliterated, term and foreign are kept.
    p4 = find(tree, "//t:p[t:term]")[0]
    assert inner(p4) == '<label>SO.</label> τὸ <term>Μ</term> γράμμα <foreign xml:lang="lat">ita</foreign> λέγεται.'
    h = result.report.hybrid
    assert h.blocks == 6 and h.spanwise == {"contains-blocks": 1}


def test_block_with_blocks_inside_stays_spanwise():
    tree = translate_document(HANDMADE, engine="tag", placement="hybrid", aligner="monotone").tree
    p = find(tree, "//t:p[t:quote]")[0]
    assert p.text == "[EN:λέγει] "
    assert find(tree, "//t:l")[0].text == "[EN:μῆνιν ἄειδε θεὰ]"   # the <l> itself is a hybrid block


def test_no_aligner_falls_back_to_spanwise():
    hybrid = translate_document(HANDMADE, engine="tag", placement="hybrid", aligner="none")
    spanwise = translate_document(HANDMADE, engine="tag", placement="spanwise")
    first = [inner(find(r.tree, "//t:text//t:p")[0]) for r in (hybrid, spanwise)]
    assert first[0] == first[1]
    assert hybrid.report.hybrid.spanwise["name:unaligned"] >= 1
    # A block without tags needs no aligner: one segment for the whole heading.
    assert find(hybrid.tree, "//t:head")[0].text == "[EN:Περὶ τοῦ πολέμου]"


def test_reordering_moves_tags_with_their_words():
    tree = translate_document(HANDMADE, engine=ReverseEngine(), placement="hybrid", aligner=ExactAligner()).tree
    p1 = find(tree, "//t:text//t:p")[0]
    assert inner(p1).startswith('ἀπῆλθεν. καὶ <name type="ethnic">Ἀθηναίοις</name> τοῖς λόγους<note')
    assert inner(p1).endswith('<num>δʹ</num> εἶπε <name type="person">Περικλῆς</name> ὁ<milestone unit="para" n="2"/>')


# -- single blocks with hand-made translations and links ------------------------------

def run(xml: str, translations: list[str], links: dict | None = None) -> str:
    """Place the tags of one <p> given its sentence translations and {sentence: links}."""
    block = etree.fromstring(f'<p xmlns="{TEI}">{xml}</p>')
    det = detag(block, policy)
    layout = Layout(det, split_sentences(det.text), translations)
    for k in layout.needs_alignment():
        layout.set_links(k, (links or {}).get(k, set()))
    placed, _ = place(layout)
    rebuild(block, layout.english, placed)
    return inner(block)


def test_wrap_covers_all_aligned_words():
    # ἴωμεν -> "let us go": the tag covers the three English words.
    out = run("ἔφη <q>ἴωμεν</q> αὐτός.", ["he said let us go himself ."],
              {0: {(0, 1), (1, 2), (1, 3), (1, 4), (2, 5), (3, 6)}})
    assert out == "he said <q>let us go</q> himself ."


def test_fixed_element_replaces_the_model_words():
    # The model wrote "Mu" for the kept <term>; it is replaced by the element with its own content.
    out = run('τὸ <term>Μ</term> γράμμα.', ["the letter Mu ."], {0: {(0, 0), (1, 2), (2, 1), (3, 3)}})
    assert out == 'the letter <term>Μ</term> .'
    # A transliterated element keeps its Greek here; its span is transliterated afterwards.
    out = run('<label>ΣΩ</label> ἔφη.', ["Soc he said ."], {0: {(0, 0), (1, 2), (2, 3)}})
    assert out == '<label>ΣΩ</label> he said .'


def test_points_left_and_right():
    out = run('ἔφη δὲ<note>n</note> λέγων <milestone unit="section" n="3"/> ταῦτα.',
              ["and he said , saying this ."],
              {0: {(0, 2), (1, 0), (2, 4), (3, 5), (4, 6)}})
    # note: after the English of δὲ ("and"); milestone: before the English of ταῦτα ("this").
    assert out == 'and<note>n</note> he said , saying <milestone unit="section" n="3"/> this .'


def test_whole_sentence_tag_needs_no_alignment():
    out = run("ἦλθεν. <q>ἴωμεν. φεύγωμεν.</q>", ["He came.", "Let us go.", "Let us flee."])
    assert out == "He came. <q>Let us go. Let us flee.</q>"


def test_between_sentences_and_boundary():
    out = run('ἦλθεν. <pb n="5"/>καὶ <lb/>εἶπεν αὐτῷ πολλά.', ["He came.", "And he told him many things."])
    assert out == 'He came. <pb n="5"/><lb/>And he told him many things.'


def test_unaligned_tag_falls_back():
    with pytest.raises(Fallback, match="q:unaligned"):
        run("ἔφη <q>ἴωμεν</q> αὐτός.", ["he said let us go himself ."], {0: {(0, 1)}})


def test_too_wide_span_falls_back():
    links = {0: {(1, 0), (1, 9)}}
    with pytest.raises(Fallback, match="q:too-wide"):
        run("ἔφη <q>ἴωμεν</q> αὐτός.", ["a b c d e f g h i j"], links)


def test_unaligned_note_goes_to_boundary():
    # Near the end of the Greek sentence -> end of the English one, and vice versa.
    out = run("ἔφη πολλὰ καὶ ἄλλα δὲ<note>n</note> λέγων.", ["he spoke many other things ."], {0: set()})
    assert out == "he spoke many other things .<note>n</note>"
    out = run("ἔφη<note>n</note> πολλὰ καὶ ἄλλα δὲ λέγων.", ["he spoke many other things ."], {0: set()})
    assert out == "<note>n</note>he spoke many other things ."


def test_crossing_siblings_fall_back():
    with pytest.raises(Fallback, match="overlap"):
        run("<q>α β</q> <hi>γ</hi>.", ["x y z ."], {0: {(0, 0), (1, 2), (2, 1), (3, 3)}})


def test_same_unit_milestones_keep_their_order():
    out = run('α <milestone unit="line" n="1"/>β γ <milestone unit="line" n="2"/>δ.', ["D B C A ."],
              {0: {(0, 3), (1, 1), (2, 2), (3, 0), (4, 4)}})
    # n=2 aligns before "D", n=1 before "B"; n=2 is moved so it does not come before n=1.
    first, second = out.index('n="1"'), out.index('n="2"')
    assert first < second


def test_point_inside_a_sibling_is_moved_out():
    out = run("<q>α β γ</q> δ<note>n</note> ε.", ["a b d c e ."],
              {0: {(0, 0), (1, 1), (2, 3), (3, 2), (4, 4), (5, 5)}})
    assert "<note>n</note>" in out and "<q>a b d c</q>" in out
    assert out.index("</q>") < out.index("<note>")
