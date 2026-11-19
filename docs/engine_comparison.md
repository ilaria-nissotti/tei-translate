# Engine comparison: Opus-MT models, the Modern Greek pivot chain and MADLAD-400

Run on 2026-11-19 with `python scripts/compare_engines.py` (seed 0), on a laptop CPU
(AMD Ryzen 7 250, 30 GB RAM, no GPU). Plain-text MT only (no XML): 54 Perseus passages
(3,238 Greek words), 8 sections from each of six prose works plus 6 Pindar odes, scored
against the Perseus English translations. All four engines translated exactly the same
passages (later engines were added with `--reuse`). Full outputs:
`outputs/compare/20261119-madlad/` (git-ignored; re-run the script to regenerate).

| Engine | Model(s) | chrF | BLEU | Time (CPU) |
|---|---|---|---|---|
| `opus-grk-en` | `Helsinki-NLP/opus-mt-grk-en` | 22.6 | 1.1 | 82 s |
| `opus-bible-ine` | `Helsinki-NLP/opus-mt-tc-bible-big-ine-deu_eng_nld` | 23.7 | 2.6 | 399 s |
| `pivot-grc-el-en` | `ilsp/nllb-200-600M-ag-mg-lora` → `Helsinki-NLP/opus-mt-tc-big-el-en` | 30.4 | 5.3 | 737 s (626 + 111) |
| **`madlad-3b`** | `google/madlad400-3b-mt` (bfloat16 on CPU) | **31.5** | **6.9** | 784 s (+ 25 s load) |

chrF per work:

| Work | n | opus-grk-en | opus-bible-ine | pivot-grc-el-en | madlad-3b |
|---|---|---|---|---|---|
| Herodotus, Histories (Ionic prose) | 8 | 24.7 | 24.0 | 39.8 | **41.6** |
| Thucydides, History (Attic prose) | 8 | 28.5 | 24.4 | 40.2 | **41.6** |
| Xenophon, Anabasis (Attic prose) | 8 | 25.0 | 28.3 | 36.7 | **39.4** |
| Plutarch, Pericles (imperial prose) | 8 | 23.6 | 27.8 | 36.9 | **38.7** |
| Josephus, Jewish Antiquities | 8 | **13.0** | 10.8 | 11.2 | 12.1 |
| Pausanias, Description of Greece | 8 | 28.7 | 31.9 | 44.0 | **45.7** |
| Pindar, Olympian Odes (whole odes) | 6 | 28.9 | 31.4 | **38.3** | 38.1 |

## Findings

- **Two usable engines, two unusable ones.** MADLAD-400 3B and the pivot chain are far
  ahead of both Opus models (+7 to +9 chrF) and usually get the meaning right. The Opus
  models mostly don't.
- **MADLAD is slightly ahead of the pivot chain** (+1.1 chrF, +1.6 BLEU) and wins five of
  the seven works, all by about 2 points. On 54 passages that's a small, consistent edge,
  not a decisive one. Example (Xenophon, *Anabasis* 1.9.3), reference: "For all the sons of
  the noblest Persians are educated at the King's court…"
  - madlad-3b: "For all the young men of the noblest of the Persians are instructed at the
    king's gates, where much wisdom is learned, but nothing ugly is heard or seen."
  - pivot-grc-el-en: "For all the sons of the best Persians are trained at the king's gates,
    where one can learn much soundness of mind, and there is nothing shameful either to hear or to see."
  - opus-bible-ine: "For all the princes of Persia, the servants of the king, are chastened at the king's doors…"
- **Both strong engines make fluent but wrong errors, of different kinds:**
  - MADLAD sometimes reads Greek words as names ("waiting for Basil" for *βασιλέα*, "the
    king"), misreads words ("setting up a troop" for *τροπαῖον*, "a trophy"), and once
    drifted into made-up Bible text: Josephus 18.11 continues with "11:11 And they said unto
    him, Thou art the king of the Jews…".
  - The chain invents or swaps names ("The Rhodesians had three paternal philosophies…" for
    *the Jews*) and garbles harder syntax ("the comedians… took great pity on him").
  - In the chain, most errors come from step 1 (Ancient → Modern Greek). The Modern Greek
    in between is saved in `translations.jsonl` (`pivot-grc-el-en (pivot)`).
- **Pindar is bad for everyone.** MADLAD leaves parts of the ode untranslated or only
  half-transliterated ("acamandopod t' apýnas ten Ψαυμιός"). Poetry is far from solved.
- **Josephus is hard for every engine** (chrF 11–13). It may be an alignment problem in the
  reference (Whiston's free 18th-century translation) rather than the MT.
- **Speed on CPU**: MADLAD (in bfloat16) and the chain both manage about 4–5 Greek words
  per second, about 10× slower than `opus-grk-en`. That's fine for passages, slow for
  whole works.
- **Practicalities**:
  - MADLAD downloads one 11.8 GB file and needs about 6 GB of RAM in bfloat16. In float32
    it would need 12 GB and run slower. Apache-2.0.
  - The chain is about 7 GB on disk. The ILSP adapter is CC BY-NC 4.0 (non-commercial):
    fine for the course project, but it would matter if the tool were reused commercially.
  - MADLAD is probably too big for the free HF Space (16 GB RAM, slow CPU); the chain might fit.

## Bugs found on the way (fixed)

- `opus-mt-tc-big-el-en` (step 2 of the chain) first produced random English words. Its
  checkpoint stores an output layer (`lm_head`) that differs from the embeddings. Older
  Transformers versions tied the two on load (overwriting the stray layer); Transformers 5
  keeps the stray one. `engines/hf.py: tie_output_embeddings` now ties them for Marian
  (Opus-MT) models. `opus-grk-en` and `opus-bible-ine` were already tied, so their scores are
  unaffected. Only step 2 was re-run on the stored Modern Greek; step 1's output and timing
  come from the original run.
- The first version of that fix tied the layers for every model whose config said so, and
  that broke MADLAD (output in Syriac and Chinese characters). Transformers 5 reports
  `tie_word_embeddings=True` for MADLAD although its `config.json` says false, and MADLAD's
  separate output layer is real. So the fix is now limited to Marian models.

## Caveats

- Small sample (54 passages): the two strong engines are close, and the ranking between
  them could flip on another sample.
- chrF/BLEU only. COMET or a human check would show the meaning errors above better.
- Famous texts: MADLAD was trained on a huge web crawl and NLLB/ILSP on a non-public
  Ancient–Modern Greek corpus, so either may have seen these texts or their translations.
  The Bible-like text in MADLAD's Josephus output suggests it has seen a lot of Koine Greek.
- Generation uses each model's defaults (beam 4, no repetition penalty).

## Implication

MADLAD-400 3B and `pivot-grc-el-en` are both reasonable default engines and run on a laptop
CPU. MADLAD is slightly better and has a simpler licence. The chain is smaller, and its
step 1 is the obvious target for fine-tuning, which is where most of its errors come from.
A larger or more varied test set (and COMET) is needed before choosing between them.
