"""MT engines behind one interface (see base.MTEngine). Pick one by name.

Named engines:
    identity, tag      test engines, no model
    opus-grk-en        Helsinki-NLP/opus-mt-grk-en (Marian, ~75M params)
    opus-bible-ine     Helsinki-NLP/opus-mt-tc-bible-big-ine-deu_eng_nld (Marian, ~0.2B)
    madlad-3b          google/madlad400-3b-mt (T5, 3B; GPU recommended)
    pivot-grc-el-en    Ancient -> Modern Greek -> English: nllb-ag-mg, then opus-el-en
    nllb-ag-mg         ilsp/nllb-200-600M-ag-mg-lora (NLLB-600M + LoRA), grc -> el only
    opus-el-en         Helsinki-NLP/opus-mt-tc-big-el-en (Marian), Modern Greek -> English

Any other Hugging Face model by prefix:
    marian:<model id>  any Opus-MT model, e.g. marian:Helsinki-NLP/opus-mt-tc-big-el-en
    madlad:<model id>  a MADLAD-400 variant, e.g. madlad:google/madlad400-7b-mt

The model engines need: pip install -e .[mt]
"""

from tei_translate.engines.chain import ChainEngine
from tei_translate.engines.hf import MadladEngine, MarianEngine, NllbLoraEngine
from tei_translate.engines.identity import IdentityEngine, TagEngine

ENGINES = {
    "identity": IdentityEngine,
    "tag": TagEngine,
    "opus-grk-en": lambda: MarianEngine("Helsinki-NLP/opus-mt-grk-en"),
    "opus-bible-ine": lambda: MarianEngine("Helsinki-NLP/opus-mt-tc-bible-big-ine-deu_eng_nld"),
    "madlad-3b": lambda: MadladEngine("google/madlad400-3b-mt"),
    "pivot-grc-el-en": lambda: ChainEngine(get_engine("nllb-ag-mg"), get_engine("opus-el-en"), pivot="el"),
    "nllb-ag-mg": lambda: NllbLoraEngine("ilsp/nllb-200-600M-ag-mg-lora"),
    "opus-el-en": lambda: MarianEngine("Helsinki-NLP/opus-mt-tc-big-el-en"),
}

PREFIXES = {"marian": MarianEngine, "madlad": MadladEngine}


def get_engine(name: str):
    if name in ENGINES:
        return ENGINES[name]()
    kind, sep, model_id = name.partition(":")
    if sep and kind in PREFIXES and model_id:
        return PREFIXES[kind](model_id)
    raise ValueError(f"unknown engine {name!r}; available: {', '.join(ENGINES)}, "
                     f"or {', '.join(p + ':<model id>' for p in PREFIXES)}")
