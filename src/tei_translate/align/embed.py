"""Word alignment from multilingual embeddings, as in SimAlign (Jalili Sabet et al. 2020).

Both sentences go through an encoder (XLM-R or a fine-tune such as
UGARIT/grc-alignment). Every subword gets its vector from one hidden layer
(layer 8 works best for XLM-R base models), the two sentences' subwords are
compared by cosine similarity, and links are read off the similarity matrix:

- argmax:  keep (i, j) when j is i's most similar target and i is j's most
           similar source (high precision);
- itermax: argmax, then repeat on the still unaligned rows/columns, so words
           left out get a second chance (better recall; the UGARIT paper
           reports its grc-en score with it).

Two words are linked when any of their subwords are. A sentence longer than
the model's input (512 subwords) gets no links, so its tags take their fallback.

Needs the MT extra (torch, transformers, sentencepiece): pip install -e .[mt]
"""

from __future__ import annotations

import logging
import time

from tei_translate.align.base import Links

log = logging.getLogger(__name__)

MAX_SUBWORDS = 510


def argmax_links(sim):
    """sim: numpy array (m x n). 0/1 matrix of mutual best matches."""
    import numpy as np

    m, n = sim.shape
    forward = np.eye(n)[sim.argmax(axis=1)]          # m x n: best target per source
    backward = np.eye(m)[sim.argmax(axis=0)].T       # m x n: best source per target
    return forward * backward


def itermax_links(sim, max_count: int = 2, alpha: float = 0.9):
    """SimAlign's IterMax: argmax, then again on what is still unaligned."""
    import numpy as np

    m, n = sim.shape
    inter = argmax_links(sim)
    if min(m, n) <= 2:
        return inter
    count = 1
    while count < max_count:
        mask_x = 1.0 - np.tile(inter.sum(1)[:, None], (1, n)).clip(0.0, 1.0)   # rows still unaligned
        mask_y = 1.0 - np.tile(inter.sum(0)[None, :], (m, 1)).clip(0.0, 1.0)   # columns still unaligned
        mask = (alpha * mask_x + alpha * mask_y).clip(0.0, 1.0)
        mask_zeros = 1.0 - (1.0 - mask_x) * (1.0 - mask_y)
        if mask_x.sum() < 1.0 or mask_y.sum() < 1.0:
            break
        new_sim = sim * mask
        forward = np.eye(n)[new_sim.argmax(axis=1)] * mask_zeros
        backward = np.eye(m)[new_sim.argmax(axis=0)].T * mask_zeros
        new_inter = forward * backward
        if not (new_inter > 0).any():
            break
        inter = (inter + new_inter).clip(0.0, 1.0)
        count += 1
    return inter


METHODS = {"argmax": argmax_links, "itermax": itermax_links}


class EmbeddingAligner:
    def __init__(self, model_id: str, *, layer: int = 8, method: str = "itermax",
                 tokenizer_id: str | None = None, batch_size: int = 16, device: str | None = None):
        """tokenizer_id: load the tokenizer from another repo with the same vocabulary (UGARIT only
        ships the old sentencepiece file, which Transformers 5 converts only with protobuf)."""
        if method not in METHODS:
            raise ValueError(f"unknown alignment method {method!r}; use one of {', '.join(METHODS)}")
        self.model_id = model_id
        self.tokenizer_id = tokenizer_id or model_id
        self.layer = layer
        self.method = method
        self.batch_size = batch_size
        self.device = device
        self.name = f"{model_id} ({method}, layer {layer})"
        self._model = None
        self._tokenizer = None

    def load(self):
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as e:
            raise ImportError(f"aligner {self.model_id} needs the MT extra: pip install -e .[mt]") from e
        from tei_translate.engines.hf import _cache_dir

        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        log.info("loading aligner %s on %s; first use downloads the model", self.model_id, device)
        cache = _cache_dir()
        self._tokenizer = AutoTokenizer.from_pretrained(self.tokenizer_id, cache_dir=cache)
        self._model = AutoModel.from_pretrained(self.model_id, cache_dir=cache).to(device).eval()
        self.device = device

    def _ids(self, words: list[str]) -> tuple[list[int], list[int]]:
        """Subword ids with the special tokens, and for each id the index of its word (-1: special)."""
        tok = self._tokenizer
        bos = tok.bos_token_id if tok.bos_token_id is not None else tok.cls_token_id
        eos = tok.eos_token_id if tok.eos_token_id is not None else tok.sep_token_id
        ids, owner = [bos], [-1]
        for w, word in enumerate(words):
            pieces = tok(word, add_special_tokens=False)["input_ids"] or [tok.unk_token_id]
            ids += pieces
            owner += [w] * len(pieces)
        return ids + [eos], owner + [-1]

    def _vectors(self, sequences: list[list[int]]) -> list:
        """Normalised layer vectors (torch tensors, special tokens included) per sequence."""
        import torch

        tok, model = self._tokenizer, self._model
        pad = tok.pad_token_id if tok.pad_token_id is not None else 0
        out = [None] * len(sequences)
        order = sorted(range(len(sequences)), key=lambda i: len(sequences[i]))
        for b in range(0, len(order), self.batch_size):
            idx = order[b:b + self.batch_size]
            longest = max(len(sequences[i]) for i in idx)
            ids = torch.full((len(idx), longest), pad, dtype=torch.long)
            mask = torch.zeros((len(idx), longest), dtype=torch.long)
            for row, i in enumerate(idx):
                ids[row, :len(sequences[i])] = torch.tensor(sequences[i])
                mask[row, :len(sequences[i])] = 1
            with torch.inference_mode():
                hidden = model(input_ids=ids.to(self.device), attention_mask=mask.to(self.device),
                               output_hidden_states=True).hidden_states[self.layer]
            for row, i in enumerate(idx):
                v = hidden[row, :len(sequences[i])].float()
                out[i] = torch.nn.functional.normalize(v, dim=-1).cpu()
        return out

    def align(self, pairs: list[tuple[list[str], list[str]]]) -> list[Links]:
        results: list[Links] = [set() for _ in pairs]
        todo = []   # (pair index, src ids, src owner, tgt ids, tgt owner)
        for p, (src, tgt) in enumerate(pairs):
            if not src or not tgt:
                continue
            if self._model is None:
                self.load()
            s_ids, s_own = self._ids(src)
            t_ids, t_own = self._ids(tgt)
            if len(s_ids) > MAX_SUBWORDS or len(t_ids) > MAX_SUBWORDS:
                log.warning("aligner: sentence too long (%d / %d subwords), not aligned", len(s_ids), len(t_ids))
                continue
            todo.append((p, s_ids, s_own, t_ids, t_own))
        if not todo:
            return results
        start = time.perf_counter()
        vectors = self._vectors([x for t in todo for x in (t[1], t[3])])
        method = METHODS[self.method]
        for n, (p, _, s_own, _, t_own) in enumerate(todo):
            sv, tv = vectors[2 * n], vectors[2 * n + 1]
            s_keep = [i for i, o in enumerate(s_own) if o >= 0]
            t_keep = [j for j, o in enumerate(t_own) if o >= 0]
            sim = (sv[s_keep] @ tv[t_keep].T).numpy()
            links = method(sim)
            rows, cols = links.nonzero()
            results[p] = {(s_own[s_keep[a]], t_own[t_keep[b]]) for a, b in zip(rows, cols)}
        log.info("aligner: %d sentence pairs in %.1fs", len(todo), time.perf_counter() - start)
        return results
