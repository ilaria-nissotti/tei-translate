# What does it cost to cut sentences at tags?

In span-wise mode, a tag in the middle of a sentence (`<pb/>`, `<q>`, `<del>`, `<note>`, ...) cuts
it in pieces, and the model translates each piece alone. How much worse does that make the
translation?

## Span-wise vs whole passages (MADLAD, 2026-11-20)

`scripts/compare_spanwise.py` translated each passage two ways and scored them with chrF against
the Perseus English. (Run with the policy of the time, when names were still transliterated.)

| Passages | n | whole | span-wise |
|---|---|---|---|
| no cut (control) | 37 | 30.3 | 30.4 |
| with a cut | 41 | 25.7 | 25.1 |
| Pindar (verse, line by line) | 6 | 38.1 | 34.9 |

- **Prose: −0.6 chrF** on passages with a cut. Small, and within noise (about ±0.4) for single
  works. Over the whole corpus 17% of blocks get cut.
- **Verse: −3.2 chrF.** Each `<l>` is translated on its own, but Greek sentences run across lines.
  This is the bigger problem.
- About a third of the cuts come from empty markers and notes, which have no words of their own.

chrF barely moves, but the broken sentences are easy to see:

- Pausanias 8.35.5: `ἐς <add>μὲν</add> Μεθύδριον` → "to 1 Methyndrion" (μέν alone became "1").
- Xenophon, Anabasis 4.1.27, cut by `<del>`: "Callimachus Parrasius opposed them Arcas and this
  one And he said…"

## Hybrid vs span-wise (pivot chain, 2026-11-20)

Hybrid mode translates whole sentences and puts the tags back with a word aligner. 16 prose
passages with cuts:

| | chrF |
|---|---|
| whole | 21.7 |
| span-wise | 21.6 |
| **hybrid** | **21.9** |

- Hybrid scores like whole-passage translation (9 of 16 outputs identical) and fixes the broken
  sentences above.
- 13 of 17 blocks were placed. Three fell back because the aligner couldn't link a one-word
  `<add>`.
- It took about 15 s longer, mostly for re-translating the blocks that fell back.

## Takeaways

- chrF is the wrong measure for this. What hybrid buys is readable sentences.
- Verse is where cutting hurts most.

Raw outputs: `outputs/spanwise/` (not in git).
