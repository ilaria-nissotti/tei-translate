"""Engine registry and the model-free parts of the Hugging Face engines.

Real models are only run when TEI_TRANSLATE_RUN_MODELS=1 is set (they download
hundreds of MB and need pip install -e .[mt]).
"""

import os

import pytest

from tei_translate.engines import get_engine
from tei_translate.engines.hf import MadladEngine, MarianEngine, split_for_mt


@pytest.mark.parametrize("name,cls,model_id", [
    ("opus-grk-en", MarianEngine, "Helsinki-NLP/opus-mt-grk-en"),
    ("opus-bible-ine", MarianEngine, "Helsinki-NLP/opus-mt-tc-bible-big-ine-deu_eng_nld"),
    ("madlad-3b", MadladEngine, "google/madlad400-3b-mt"),
    ("marian:Helsinki-NLP/opus-mt-tc-big-el-en", MarianEngine, "Helsinki-NLP/opus-mt-tc-big-el-en"),
    ("madlad:google/madlad400-7b-mt", MadladEngine, "google/madlad400-7b-mt"),
])
def test_registry(name, cls, model_id):
    engine = get_engine(name)
    assert isinstance(engine, cls)
    assert engine.name == model_id
    assert engine._model is None  # nothing loaded until translate()


@pytest.mark.parametrize("name", ["nope", "marian:", "foo:bar"])
def test_unknown_engine(name):
    with pytest.raises(ValueError):
        get_engine(name)


def test_split_sentences():
    text = "ὁ μὲν ἦλθεν.  ὁ δὲ\n  ἀπῆλθεν; τί ἔστι"
    assert split_for_mt(text) == ["ὁ μὲν ἦλθεν.", "ὁ δὲ ἀπῆλθεν;", "τί ἔστι"]


def test_split_greek_question_mark():
    assert split_for_mt("τί λέγεις; οὐδέν.") == ["τί λέγεις;", "οὐδέν."]


def test_split_long_sentence_at_clauses_then_words():
    text = "α β γ, δ ε· ζ η θ ι κ λ."
    pieces = split_for_mt(text, max_len=3)
    assert all(len(p.split()) <= 3 for p in pieces)
    assert " ".join(pieces) == text  # nothing lost or reordered
    assert pieces[:2] == ["α β γ,", "δ ε·"]


def test_split_empty():
    assert split_for_mt("  \n ") == []


def test_no_split_when_short():
    assert split_for_mt("α, β· γ", max_len=10) == ["α, β· γ"]


class FakeTokenizer:
    def __init__(self, vocab):
        self.vocab = {t: i for i, t in enumerate(vocab)}

    def get_vocab(self):
        return self.vocab


def test_marian_prefix():
    engine = MarianEngine("x")
    engine._tokenizer = FakeTokenizer(["a", ">>deu<<", ">>eng<<", ">>nld<<"])
    assert engine.prefix("grc", "en") == ">>eng<< "
    engine._tokenizer = FakeTokenizer(["a", "b"])  # single-target model
    assert engine.prefix("grc", "en") == ""
    engine._tokenizer = FakeTokenizer([">>deu<<"])
    with pytest.raises(ValueError):
        engine.prefix("grc", "en")
    assert MarianEngine("x", target_token=">>eng<<").prefix("grc", "en") == ">>eng<< "


def test_madlad_prefix():
    engine = MadladEngine()
    engine._tokenizer = FakeTokenizer(["<2en>", "<2de>"])
    assert engine.prefix("grc", "en") == "<2en> "
    with pytest.raises(ValueError):
        engine.prefix("grc", "fr")


class FakeEngine(MarianEngine):
    """Marian engine with the model replaced: 'translates' by upper-casing, counts calls."""

    def __init__(self):
        super().__init__("fake", max_input_tokens=4)
        self._tokenizer = FakeTokenizer(["a"])
        self._model = object()
        self.sent = []

    def n_tokens(self, text):
        return len(text.split())

    def _generate(self, texts):
        self.sent += texts
        return [t.upper() for t in texts]


def test_translate_splits_joins_and_dedupes():
    engine = FakeEngine()
    out = engine.translate(["ab cd. ef.", "ef.", ""], "grc", "en")
    assert out == ["AB CD. EF.", "EF.", ""]
    assert engine.sent == ["ab cd.", "ef."]  # "ef." translated once


@pytest.mark.skipif(os.environ.get("TEI_TRANSLATE_RUN_MODELS") != "1",
                    reason="set TEI_TRANSLATE_RUN_MODELS=1 to run real models")
@pytest.mark.parametrize("name", ["opus-grk-en", "opus-bible-ine"])
def test_real_opus_model_through_pipeline(name):
    from pathlib import Path

    from tei_translate.pipeline.document import translate_document

    fixture = Path(__file__).parent / "fixtures" / "tei" / "lucian_excerpt.xml"
    result = translate_document(fixture, engine=name)
    failed = {k: v for k, v in result.report.checks.items() if not v["ok"]}
    assert not failed, result.report.summary()
