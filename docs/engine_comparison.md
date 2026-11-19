# Engine comparison: Opus-MT models and the Modern Greek pivot chain

Run on 2026-11-19 with `python scripts/compare_engines.py` (seed 0), on a laptop CPU.
Plain-text MT only (no XML): 54 Perseus passages (3,238 Greek words), 8 sections from each
of six prose works plus 6 Pindar odes, scored against the Perseus English translations.
All three engines translated exactly the same passages (the pivot chain was added with
`--reuse`). Full outputs: `outputs/compare/20261119-pivot/` (git-ignored; re-run the script
to regenerate).

| Engine | Model(s) | chrF | BLEU | Time (CPU) |
|---|---|---|---|---|
| `opus-grk-en` | `Helsinki-NLP/opus-mt-grk-en` | 22.6 | 1.1 | 82 s |
| `opus-bible-ine` | `Helsinki-NLP/opus-mt-tc-bible-big-ine-deu_eng_nld` | 23.7 | 2.6 | 399 s |
| **`pivot-grc-el-en`** | `ilsp/nllb-200-600M-ag-mg-lora` → `Helsinki-NLP/opus-mt-tc-big-el-en` | **30.4** | **5.3** | 737 s (626 + 111) |

chrF per work:

| Work | n | opus-grk-en | opus-bible-ine | pivot-grc-el-en |
|---|---|---|---|---|
| Herodotus, Histories (Ionic prose) | 8 | 24.7 | 24.0 | **39.8** |
| Thucydides, History (Attic prose) | 8 | 28.5 | 24.4 | **40.2** |
| Xenophon, Anabasis (Attic prose) | 8 | 25.0 | 28.3 | **36.7** |
| Plutarch, Pericles (imperial prose) | 8 | 23.6 | 27.8 | **36.9** |
| Josephus, Jewish Antiquities | 8 | **13.0** | 10.8 | 11.2 |
| Pausanias, Description of Greece | 8 | 28.7 | 31.9 | **44.0** |
| Pindar, Olympian Odes (whole odes) | 6 | 28.9 | 31.4 | **38.3** |

## Findings

- **The pivot chain is clearly the best of the three**: +6.7 chrF overall, and +8 to +16
  on every work except Josephus. Unlike the Opus models, it usually gets the meaning right.
  Example (Xenophon, *Anabasis* 1.9.3), reference: "For all the sons of the noblest
  Persians are educated at the King's court…"
  - pivot-grc-el-en: "For all the sons of the best Persians are trained at the king's gates, where
    one can learn much soundness of mind, and there is nothing shameful either to hear or to see."
  - opus-bible-ine: "For all the princes of Persia, the servants of the king, are chastened at the king's doors…"
- **The Modern Greek in between is often very good.** Most errors come from step 1
  (Ancient → Modern Greek), not from step 2. The intermediate text is saved in
  `translations.jsonl` (`pivot-grc-el-en (pivot)`).
- **Its errors are dangerous because they read fluently.** It invents or swaps names
  ("The Rhodesians had three paternal philosophies…" for *the Jews* in Josephus; "the
  Rhodians" for the people of Aphytis in Pausanias) and gets harder syntax wrong (the
  Plutarch passage comes out as "the comedians… took great pity on him").
- **Josephus is hard for every engine** (chrF 11–13). Worth looking into: it may be an
  alignment problem in the reference (Whiston's free 18th-century translation) rather than
  the MT.
- **Pindar is better, but not good**: the ode comes out as loose word salad. Poetry is far
  from solved.
- **Speed**: the chain is about 9× slower than `opus-grk-en` on CPU, almost all of it in
  the NLLB step (626 s for 3,238 words, about 5 words/s). That's fine for passages and
  slow for whole works without a GPU.
- **Licence**: the ILSP adapter is CC BY-NC 4.0 (non-commercial). That's fine for the
  course project; it would matter if the tool were reused commercially.

## Bug found on the way (fixed)

`opus-mt-tc-big-el-en` first produced random English words. Its checkpoint stores an
output layer (`lm_head`) that differs from the embeddings, although its config says the
two are tied. Older Transformers versions tied them on load (overwriting the stray layer);
Transformers 5 keeps the stray one. `engines/hf.py: tie_output_embeddings` now ties them
whenever the config asks for it, and logs a warning. `opus-grk-en` and `opus-bible-ine` were
already tied, so their scores are unaffected. Only step 2 was re-run on the stored Modern
Greek; the step 1 output and its timing come from the original run.

## Caveats

- Small sample (54 passages): the pivot chain's lead is large and consistent across works,
  but the exact numbers are rough.
- chrF/BLEU only. COMET or a human check would show the meaning errors above better.
- Famous texts: little contamination risk for these models, but some for NLLB/ILSP, whose
  Ancient–Modern Greek training corpus is not public.
- Generation uses each model's defaults (beam 4, no repetition penalty).

## Implication

`pivot-grc-el-en` is the best engine we can run today without a GPU, and a reasonable default for
the pipeline and the CPU-only HF Space (with patience). MADLAD-400 3B is still untested
(needs a GPU or Colab). The planned fine-tuning could target step 1 directly, because that's
where most errors come from.
