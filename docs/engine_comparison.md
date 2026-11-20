# Which translation model?

Run on 2026-11-19 with `scripts/compare_engines.py` on a laptop CPU (Ryzen 7 250, 30 GB RAM, no
GPU). Plain text only, no XML: 54 Perseus passages (3,238 Greek words), 8 from each of six prose
works plus 6 Pindar odes, scored against the Perseus English translations.

| Engine | chrF | BLEU | Time |
|---|---|---|---|
| `opus-grk-en` | 22.6 | 1.1 | 82 s |
| `opus-bible-ine` | 23.7 | 2.6 | 399 s |
| `pivot-grc-el-en` (Ancient → Modern Greek → English) | 30.4 | 5.3 | 737 s |
| **`madlad-3b`** | **31.5** | **6.9** | 784 s |

chrF per work:

| Work | opus-grk-en | opus-bible-ine | pivot | madlad |
|---|---|---|---|---|
| Herodotus | 24.7 | 24.0 | 39.8 | **41.6** |
| Thucydides | 28.5 | 24.4 | 40.2 | **41.6** |
| Xenophon, Anabasis | 25.0 | 28.3 | 36.7 | **39.4** |
| Plutarch, Pericles | 23.6 | 27.8 | 36.9 | **38.7** |
| Josephus | **13.0** | 10.8 | 11.2 | 12.1 |
| Pausanias | 28.7 | 31.9 | 44.0 | **45.7** |
| Pindar (whole odes) | 28.9 | 31.4 | **38.3** | 38.1 |

## What we saw

- MADLAD and the pivot chain are far better than the Opus models and usually get the meaning
  right. MADLAD is a little ahead (5 of 7 works), but on 54 passages that's close to noise.
- Both make fluent mistakes. MADLAD sometimes reads words as names ("waiting for Basil" for
  βασιλέα, "the king") and once drifted into made-up Bible verses. The chain swaps names
  ("Rhodesians" for "Jews"); most of its errors come from the first step.
- Pindar is bad for everyone; MADLAD leaves parts untranslated.
- Josephus is bad for everyone, maybe because the reference translation is very free.
- The Opus models loop on text they don't understand (e.g. Homer).

## On the free Hugging Face Space

The free Space has 2 CPU cores and 16 GB RAM. We tested with 2 threads
(`scripts/bench_engine_threads.py`, 11 passages):

| Engine | Speed | Peak memory |
|---|---|---|
| `pivot-grc-el-en` | 2.0 words/s | 9.2 GB |
| `madlad-3b` | 1.75 words/s | 11.9 GB |

Both fit, and a 100-word passage takes about a minute. Not tested yet: the Space's own CPU (if it
handles bfloat16 badly, MADLAD could be much slower there) and the start-up time after the Space
sleeps.

## Decision (2026-11-20)

**`madlad-3b` is the default**, locally and on the Space. It scores a bit higher, has a simple
licence (Apache 2.0; the chain's adapter is non-commercial), and is one model instead of two.
`pivot-grc-el-en` is the fallback.

Switch to the chain if MADLAD is too slow on the Space, or if we fine-tune (its 600M first step is
much easier to train than a 3B model).

## Two bugs we hit

- `opus-mt-tc-big-el-en` produced random words with Transformers 5, because its output layer
  wasn't tied to its embeddings anymore. Fixed for Marian models in `engines/hf.py`.
- Applying that fix to every model broke MADLAD, whose separate output layer is real. So the fix
  only applies to Marian models.

## Caveats

Small sample, chrF/BLEU only (COMET or a human check would catch meaning errors better), and the
models may have seen these famous texts during training.
