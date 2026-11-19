# Engine comparison: Opus-MT models (first run)

Run on 2026-11-19 with `python scripts/compare_engines.py` (seed 0), on a laptop CPU.
Plain-text MT only (no XML): 54 Perseus passages (3,238 Greek words), 8 sections from each
of six prose works plus 6 Pindar odes, scored against the Perseus English translations.
Full outputs: `outputs/compare/20261119-192544/` (git-ignored; re-run the script to regenerate).

| Engine | Model | Size | chrF | BLEU | Time (CPU) |
|---|---|---|---|---|---|
| `opus-grk-en` | `Helsinki-NLP/opus-mt-grk-en` | ~75M params | 22.6 | 1.1 | 82 s |
| `opus-bible-ine` | `Helsinki-NLP/opus-mt-tc-bible-big-ine-deu_eng_nld` | ~0.2B params | 23.7 | 2.6 | 399 s |

chrF per work:

| Work | n | opus-grk-en | opus-bible-ine |
|---|---|---|---|
| Herodotus, Histories (Ionic prose) | 8 | 24.7 | 24.0 |
| Thucydides, History (Attic prose) | 8 | 28.5 | 24.4 |
| Xenophon, Anabasis (Attic prose) | 8 | 25.0 | 28.3 |
| Plutarch, Pericles (imperial prose) | 8 | 23.6 | 27.8 |
| Josephus, Jewish Antiquities | 8 | 13.0 | 10.8 |
| Pausanias, Description of Greece | 8 | 28.7 | 31.9 |
| Pindar, Olympian Odes (whole odes) | 6 | 28.9 | 31.4 |

## Findings

- **Neither model is usable for Ancient Greek.** Outputs share a few content words and
  proper names with the reference, but the meaning is mostly wrong. Example (Xenophon,
  *Anabasis* 1.9.3), reference: "For all the sons of the noblest Persians are educated at
  the King's court…"
  - opus-grk-en: "All the kings of Persians, when the kings are disciplined, are trained…"
  - opus-bible-ine: "For all the princes of Persia, the servants of the king, are chastened at the king's doors…"
- **The difference between them is within noise.** +1.1 chrF over 54 passages, and the
  per-work winner switches back and forth.
- **opus-bible-ine writes like the Bible.** Expected from its training data: "And when
  they had heard the word…", and it brings in Bible material that isn't in the text
  ("the Good News", Lystra, Phinehas). That's dangerous for a scholarly tool, because the
  output reads fluently.
- **Both get stuck in loops** on hard input ("in the mountains, in the mountains, …";
  "on the west side, and on the west side, …"), especially in Pindar. Long looping output
  can *inflate* chrF (more character n-grams that happen to match), so the Pindar scores
  look better than the outputs are.
- **opus-bible-ine is about 5× slower** on CPU (big transformer, longer outputs).
- Both models ran through the full TEI pipeline on `tests/fixtures/tei/lucian_excerpt.xml`
  and all validation checks passed (`TEI_TRANSLATE_RUN_MODELS=1 pytest tests/test_engines.py`).

## Caveats

- Small sample (54 passages). Treat the numbers as an order of magnitude, not a ranking.
- Generation uses each model's defaults (beam 4, no repetition penalty). A repetition
  penalty or `no_repeat_ngram_size` would cut the loops, but it wouldn't fix the meaning.
- Herodotus, Thucydides, Xenophon etc. are famous texts. Contamination matters little for
  these models but will matter for MADLAD and LLMs.

## Implication

Opus-MT models are good for testing the plumbing, not for translating. The next candidates
are MADLAD-400 3B (needs a GPU or Colab) and the pivot chain via Modern Greek, then
fine-tuning, as planned in `HANDOVER.md`.
