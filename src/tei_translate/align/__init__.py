"""Word aligners behind one interface (see base.Aligner). Pick one by name.

Named aligners:
    none        links nothing (every tag needing alignment takes its fallback)
    monotone    diagonal links, for tests with the identity engine
    ugarit      UGARIT/grc-alignment: XLM-R base fine-tuned for Ancient Greek alignment
                (CC BY 4.0, 1.1 GB; IterMax, layer 8)
    dragoman    open-greek/dragoman: a further fine-tune of UGARIT (CC BY 4.0; ArgMax, layer 8)
    xlmr        xlm-roberta-base, for other language pairs (IterMax, layer 8)

Any other encoder by prefix:
    embed:<model id>   SimAlign-style alignment with that model (IterMax, layer 8)

The model aligners need: pip install -e .[mt]
"""

from __future__ import annotations

from tei_translate.align.base import Aligner, Links, word_spans  # noqa: F401
from tei_translate.align.embed import EmbeddingAligner
from tei_translate.align.simple import MonotoneAligner, NoAligner

ALIGNERS = {
    "none": NoAligner,
    "monotone": MonotoneAligner,
    # Same sentencepiece vocabulary as XLM-R base (identical file); its tokenizer.json loads without protobuf.
    "ugarit": lambda: EmbeddingAligner("UGARIT/grc-alignment", method="itermax",
                                       tokenizer_id="FacebookAI/xlm-roberta-base"),
    "dragoman": lambda: EmbeddingAligner("open-greek/dragoman", method="argmax"),
    "xlmr": lambda: EmbeddingAligner("xlm-roberta-base", method="itermax"),
}

PREFIXES = {"embed": EmbeddingAligner}


def get_aligner(name: str):
    if name in ALIGNERS:
        return ALIGNERS[name]()
    kind, sep, model_id = name.partition(":")
    if sep and kind in PREFIXES and model_id:
        return PREFIXES[kind](model_id)
    raise ValueError(f"unknown aligner {name!r}; available: {', '.join(ALIGNERS)}, "
                     f"or {', '.join(p + ':<model id>' for p in PREFIXES)}")
