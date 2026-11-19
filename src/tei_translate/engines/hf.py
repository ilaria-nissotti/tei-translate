"""Hugging Face seq2seq MT engines: any Opus-MT (Marian) model, and MADLAD-400.

Needs the optional extra (torch, transformers, sentencepiece):

    pip install -e .[mt]

Nothing heavy is imported until the first translate() call, so the pipeline and
the test engines keep working without the extra.

Models are downloaded on first use into models/hf/ (git-ignored), unless HF_HOME
or HF_HUB_CACHE is set, in which case the usual Hugging Face cache is used.

Segments from the pipeline can be whole paragraphs. These models are trained on
sentences and cut off long input, so each segment is split into sentences
(and over-long sentences into clauses, then words), translated piece by piece,
and joined back with spaces. Identical pieces are translated only once.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Callable

from tei_translate.pipeline.policy import REPO_ROOT

log = logging.getLogger(__name__)

# Sentence ends: . ! ? and the Greek question mark (";" U+003B or U+037E).
SENTENCE_END = re.compile(r"(?<=[.!?;;])\s+")
# Weaker breaks for over-long sentences: comma, colon, Greek ano teleia (U+0387, U+00B7).
SOFT_BREAK = re.compile(r"(?<=[,:··])\s+")
WORD_BREAK = re.compile(r"\s+")
BREAKS = [SENTENCE_END, SOFT_BREAK, WORD_BREAK]

# ISO 639-1 -> 639-3, for Opus-MT target tokens such as >>eng<<.
ISO3 = {"en": "eng", "de": "deu", "nl": "nld", "fr": "fra", "it": "ita", "es": "spa",
        "el": "ell", "la": "lat", "pt": "por", "ru": "rus"}


def _word_count(text: str) -> int:
    return len(text.split())


def split_for_mt(text: str, length: Callable[[str], int] = _word_count, max_len: int = 200) -> list[str]:
    """Split text into sentences; split sentences longer than max_len further.

    `length` measures a piece (the engines use the model's token count). Every
    sentence becomes its own piece; only a sentence over max_len is broken at
    commas/colons/ano teleia, and a clause still over max_len at word boundaries.
    Whitespace is normalised to single spaces. Empty text gives [].
    """
    text = " ".join(text.split())
    if not text:
        return []
    return [p for sentence in SENTENCE_END.split(text) for p in _fit(sentence, length, max_len, 1)]


def _fit(text: str, length, max_len: int, level: int) -> list[str]:
    if level >= len(BREAKS) or length(text) <= max_len:
        return [text]
    pieces, current = [], ""
    for part in BREAKS[level].split(text):
        candidate = f"{current} {part}" if current else part
        if current and length(candidate) > max_len:
            pieces.append(current)
            current = part
        else:
            current = candidate
    if current:
        pieces.append(current)
    return [p for piece in pieces for p in _fit(piece, length, max_len, level + 1)]


def _cache_dir():
    if os.environ.get("HF_HOME") or os.environ.get("HF_HUB_CACHE"):
        return None
    path = REPO_ROOT / "models" / "hf"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


class HFSeq2SeqEngine:
    """Any Hugging Face encoder-decoder translation model (AutoModelForSeq2SeqLM).

    Subclasses only decide what goes in front of each input (target-language token)
    and which dtype to use on GPU.
    """

    def __init__(self, model_id: str, *, batch_size: int = 8, num_beams: int = 4,
                 max_input_tokens: int = 200, device: str | None = None):
        self.model_id = model_id
        self.name = model_id   # recorded in the output's respStmt
        self.batch_size = batch_size
        self.num_beams = num_beams
        self.max_input_tokens = max_input_tokens
        self.device = device
        self._model = None
        self._tokenizer = None

    # -- loading -------------------------------------------------------------

    def _gpu_dtype(self, torch):
        return torch.float16

    def load(self):
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except ImportError as e:
            raise ImportError(f"engine {self.model_id} needs the MT extra: pip install -e .[mt]") from e
        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        dtype = self._gpu_dtype(torch) if device == "cuda" else torch.float32
        log.info("loading %s on %s (%s); first use downloads the model", self.model_id, device, dtype)
        cache = _cache_dir()
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id, cache_dir=cache)
        model = AutoModelForSeq2SeqLM.from_pretrained(self.model_id, cache_dir=cache, dtype=dtype)
        self._model = model.to(device).eval()
        self.device = device

    # -- per-model input prefix ----------------------------------------------

    def prefix(self, src: str, tgt: str) -> str:
        """Text put in front of every input (e.g. a target-language token)."""
        return ""

    def _has_token(self, token: str) -> bool:
        tok = self._tokenizer
        return token in tok.get_vocab()

    # -- translation ---------------------------------------------------------

    def n_tokens(self, text: str) -> int:
        return len(self._tokenizer(text, add_special_tokens=False).input_ids)

    def translate(self, segments: list[str], src: str, tgt: str) -> list[str]:
        if not segments:
            return []
        self.load()
        prefix = self.prefix(src, tgt)
        plans = [split_for_mt(s, self.n_tokens, self.max_input_tokens) for s in segments]
        unique = list(dict.fromkeys(p for plan in plans for p in plan))
        log.info("%s: %d segments -> %d pieces to translate", self.model_id, len(segments), len(unique))
        start = time.perf_counter()
        outputs = self._generate([prefix + p for p in unique])
        log.info("%s: translated in %.1fs", self.model_id, time.perf_counter() - start)
        done = dict(zip(unique, outputs))
        return [" ".join(done[p] for p in plan) for plan in plans]

    def _generate(self, texts: list[str]) -> list[str]:
        import torch

        tok, model = self._tokenizer, self._model
        # Sort by length so each batch pads little; restore order at the end.
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        results = [""] * len(texts)
        for b in range(0, len(order), self.batch_size):
            idx = order[b:b + self.batch_size]
            enc = tok([texts[i] for i in idx], return_tensors="pt", padding=True, truncation=True,
                      max_length=self.max_input_tokens + 16).to(self.device)
            max_new = min(512, 2 * enc["input_ids"].shape[1] + 16)
            with torch.inference_mode():
                out = model.generate(**enc, num_beams=self.num_beams, max_new_tokens=max_new)
            for i, text in zip(idx, tok.batch_decode(out, skip_special_tokens=True)):
                results[i] = text.strip()
        return results


class MarianEngine(HFSeq2SeqEngine):
    """Any Opus-MT model (Helsinki-NLP/opus-mt-*), all of which are Marian models.

    Models with several target languages need a token like >>eng<< in front of
    the input; it is found from the tokenizer's vocabulary, or set it with
    `target_token`. Single-target models (e.g. opus-mt-grk-en) get no prefix.
    """

    def __init__(self, model_id: str, *, target_token: str | None = None, **kwargs):
        super().__init__(model_id, **kwargs)
        self.target_token = target_token

    def prefix(self, src: str, tgt: str) -> str:
        if self.target_token:
            return self.target_token + " "
        codes = {t for t in self._tokenizer.get_vocab() if t.startswith(">>") and t.endswith("<<")}
        if not codes:
            return ""
        for code in (tgt, ISO3.get(tgt)):
            if code and f">>{code}<<" in codes:
                return f">>{code}<< "
        raise ValueError(f"{self.model_id} needs a target token, none found for {tgt!r}; "
                         f"available: {', '.join(sorted(codes)[:20])}")


class MadladEngine(HFSeq2SeqEngine):
    """MADLAD-400 (google/madlad400-*-mt): a T5 model, input prefixed with <2xx>.

    3B parameters: about 12 GB of RAM in float32 on CPU (slow), bfloat16 on GPU.
    """

    def __init__(self, model_id: str = "google/madlad400-3b-mt", **kwargs):
        kwargs.setdefault("batch_size", 4)
        super().__init__(model_id, **kwargs)

    def _gpu_dtype(self, torch):
        # T5 models overflow in float16; bfloat16 is safe where supported.
        return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float32

    def prefix(self, src: str, tgt: str) -> str:
        token = f"<2{tgt}>"
        if not self._has_token(token):
            raise ValueError(f"{self.model_id} has no target token {token}")
        return token + " "
