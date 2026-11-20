# What does span-wise translation cost?

Run on 2026-11-20 with `scripts/compare_spanwise.py`, engine `madlad-3b` (bfloat16, laptop CPU).
Question: the pipeline translates each text piece where it is, so an element in the middle
of a sentence (`<pb/>`, `<milestone/>`, `<q>`, `<del>`, `<note>`, ...) cuts the sentence and the
model translates the pieces separately. How much quality does that lose compared with
translating the whole passage (the best an aligner could do)?

Each passage (a leaf textpart `<div>`, as in `compare_engines.py`) is translated three ways and
scored against the Perseus English (chrF / BLEU, notes, bibl and head removed on both sides):

- **whole**: the passage's plain text in one piece (upper bound for an aligner)
- **split**: cut where the pipeline cuts, but every piece is translated (fragmentation only)
- **pipeline**: the real span-wise pipeline with `config/policy.yaml` (names transliterated, `num`/`bibl`/`foreign` kept)

Two passage sets:
- the 54 random passages from the engine comparison (`whole` reused from `outputs/compare/20261119-madlad`),
  of which 12 have a cut;
- 32 passages that all have a cut (up to 6 per work, seed 0).

Outputs: `outputs/spanwise/20261120-madlad-random/` and `outputs/spanwise/20261120-madlad-split/` (git-ignored).

## Results

| Set (prose only, Pindar separate) | n | whole | split | pipeline |
|---|---|---|---|---|
| **Control:** no cut, one block | 37 | 30.3 | 30.4 | 30.4 |
| **Passages with a cut** (both sets, deduplicated) | 41 | 25.7 | 25.1 | 25.1 |
| Pindar, whole odes (random set) | 6 | 38.1 | 34.9 | 34.9 |

Corpus chrF. The control group shows the noise: the same input in a different batch gives
slightly different bfloat16 output (19 of 37 identical), worth about ±0.4 chrF per work.

- **Prose, inline cuts: −0.6 chrF** on the passages that have a cut. Per passage, 9 of 41
  lose more than 2 chrF (3 gain more than 2); in the control group it is 1 of 37 (3 gain).
  The cost is small on average but real.
- **Corpus-wide the average effect is small.** 22% of the random passages have a cut, so the average prose
  loss is about 0.1–0.2 chrF. Over all 626 Greek Perseus files (`collect_spans` with
  `config/policy.yaml`), 37,352 of 220,504 blocks (17%) reach the model in more than one piece,
  but those pieces make up 57% of everything sent to the model.
- **Verse: −3.2 chrF.** In Pindar each `<l>` is its own block, so the pipeline translates line
  by line, while `whole` translates sentences across lines. This is not caused by inline tags.
  It is the block choice for verse, and it costs five times more than the inline cuts.
- **split = pipeline.** The special treatments (transliterating names, keeping numbers) make no
  measurable difference here: these editions have few `<name>`/`<num>` tags (outputs differ in
  2 of 54 and 8 of 32 passages).
- **What cuts the prose passages:** `q` (10), `del` (9), `milestone` (9), `pb` (8), `add` (5),
  `note` (4), `foreign` (3), then single cases (passages containing each element inside a cut
  block). About a third are empty markers or notes (`milestone`, `pb`, `note`, `gap`), which
  carry no words of their own.

## What goes wrong when a sentence is cut

chrF barely moves, but the errors are visible to a reader:

- A lone word translated out of context: Pausanias 8.35.5, `ἐς <add>μὲν</add> Μεθύδριον` →
  "to 1 Methyndrion" (the particle μέν alone became "1").
- Broken word order around a tag: Xenophon, *Anabasis* 4.1.27, `Καλλίμαχος Παρράσιος <del>Ἀρκὰς
  καὶ οὗτος</del> ἔφη…` → "Callimachus Parrasius opposed them Arcas and this one And he said…"
  (whole: "but Callimachus Parrasius Arcas, resisting them, said that he also would go").
- A clause cut by a note anchor and a `<gap/>`: Herodotus 4.47.2 → "them I call Istros was the
  fifth-mouthed" (whole: "these I call Istros the Pentastomos").

## What this means for the aligner

- **For prose, an aligner can win back at most about 0.6 chrF on affected passages** with this
  engine. chrF is the wrong measure for its main benefit, which is no broken sentences.
  Readability would need a human check on a few passages.
- **A cheap first step without an aligner:** about a third of the cuts come from empty markers
  and notes (and corpus-wide `milestone`, `pb` and `lb` are the most frequent elements in cut blocks). If those were moved to the nearest sentence boundary (the 🟡 proposal in
  `tag_decisions.md` §3), the sentence would no longer be cut, with no alignment model.
- **Verse is where span-wise really hurts.** Translating a sentence across `<l>` lines and then
  splitting the English back into lines is itself an alignment problem: line-boundary
  projection. HANDOVER defers verse, but by this measure it is the bigger win.

## Caveats

- One engine and 41 + 6 passages; differences under about 0.5 chrF are within the noise.
- Josephus references are poor (chrF about 10 for every condition), so they add noise but
  no signal.
- `whole` joins a passage's blocks. For multi-block prose passages this also removes block
  boundaries, but paragraphs end at sentence ends, so that has little effect.

## Hybrid placement with the pivot model (2026-11-20)

After the hybrid mode was built (tags removed, sentences translated whole, tags put back with
the `UGARIT/grc-alignment` word aligner; see `CLAUDE.md`), `compare_spanwise.py` got a fourth
condition, **hybrid**, which runs the real hybrid pipeline. Blocks it cannot place go span-wise,
as in the pipeline.

Run: engine `pivot-grc-el-en`, every second passage of the 32 cut passages above
(`--reuse outputs/spanwise/20261120-madlad-split --every 2`): 16 passages, 852 Greek words,
all prose. Output: `outputs/spanwise/20261120-pivot-half/` (git-ignored).

| Condition | chrF | BLEU | Time (s) |
|---|---|---|---|
| whole | 21.7 | 3.3 | 169 |
| split | 21.6 | 3.4 | 171 |
| pipeline (span-wise) | 21.6 | 3.4 | 184 |
| **hybrid** | **21.9** | 3.2 | 198 |

- **Hybrid matches whole-passage translation** (9 of 16 outputs identical to `whole`) and is
  0.3 chrF above span-wise. That is within the noise (about ±0.4), as expected from the MADLAD
  result above: chrF barely sees the broken sentences.
- **Per passage**, hybrid beats span-wise by more than 2 chrF in 2 passages and loses by more
  than 2 in 2. The wins are where cuts broke the sentence: Xenophon 4.1.27, cut by `del`
  (34.3 → 41.4, the fragments "It lasts. … He's good too." are gone); Herodotus 4.47.2, cut by
  `gap`/`note` (32.7 → 35.8). The losses are passages where the pivot's whole-sentence
  translation happens to be worse than its pieces (Xenophon 3.4.16, cut by `sic`: 45.7 → 36.1,
  although the span-wise text ends with a dangling "Archers;").
- **Placement:** 13 of 17 blocks placed in hybrid mode. Three fell back to span-wise because
  UGARIT could not align a one-word `<add>` (2 unaligned, 1 too wide); one block contains
  other blocks.
- **Cost:** about 15 s more than span-wise, mostly the second engine batch for the blocks
  that fell back; the aligner took 1.4 s.
