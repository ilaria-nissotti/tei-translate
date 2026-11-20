"""TEI schema check (tei_all via lxml): valid output, errors inherited from the source, new errors."""

import copy
from pathlib import Path

from lxml import etree

from tei_translate.pipeline.document import translate_document
from tei_translate.pipeline.validate import DEFAULT_SCHEMA, schema_check, schema_errors

FIXTURES = Path(__file__).parent / "fixtures" / "tei"
LUCIAN = FIXTURES / "lucian_excerpt.xml"
HANDMADE = FIXTURES / "handmade.xml"
TEI = "{http://www.tei-c.org/ns/1.0}"
CHECK = "TEI schema (tei_all)"


def first_p(tree):
    return next(tree.getroot().iter(f"{TEI}p"))


def test_schema_file_is_pinned():
    assert DEFAULT_SCHEMA.exists()
    assert "TEI Edition: P5 Version\xa04.12.0" in DEFAULT_SCHEMA.read_text(encoding="utf-8")[:2000]


def test_valid_source_gives_valid_output():
    result = translate_document(LUCIAN, engine="tag", aligner="monotone")
    assert result.report.checks[CHECK] == {"ok": True, "detail": "valid"}


def test_errors_already_in_source_are_accepted():
    source = etree.parse(str(HANDMADE))
    assert schema_errors(source)  # <unknownTag> is not TEI
    result = translate_document(HANDMADE, engine="tag", aligner="monotone")
    check = result.report.checks[CHECK]
    assert check["ok"] and "source already invalid" in check["detail"]


def test_new_error_fails():
    source = etree.parse(str(LUCIAN))
    output = copy.deepcopy(source)
    etree.SubElement(first_p(output), f"{TEI}notATeiElement").text = "x"
    check = schema_check(source, output)
    assert not check["ok"] and check["detail"].startswith("1 new errors")


def test_invalid_attribute_value_fails():
    source = etree.parse(str(LUCIAN))
    output = copy.deepcopy(source)
    first_p(output).set("{http://www.w3.org/XML/1998/namespace}lang", "not a language tag")
    assert not schema_check(source, output)["ok"]


def test_schema_can_be_skipped():
    pair = {"src": "grc", "tgt": "en", "placement": "spanwise", "schema": None}
    result = translate_document(LUCIAN, pair=pair, engine="identity")
    assert CHECK not in result.report.checks
