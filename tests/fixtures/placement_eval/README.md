# Test data for the tag-placement evaluation

Used by `tests/test_placement_eval.py` to test `src/tei_translate/metrics/placement_eval.py`, and to try `scripts/eval_placement.py` without the real gold set (`--gold-dir tests/fixtures/placement_eval/gold --perseus tests/fixtures/placement_eval/perseus`). It is **not** part of the gold set, which lives in `data/gold/grc-en/`.

The layout is the same as the real data:
- `perseus/texts/test.test001/greek/test.test001.perseus-grc1.xml`: a hand-made Greek TEI file;
- `gold/test.test001.perseus-grc1.en.xml`: its gold translation, with the same tags;
- `gold/translations.csv`: the index, in the format of `docs/gold_set_handover.md` (status `partial`, because one paragraph is left in Greek on purpose).

Each English sentence has the same words in the same order as the Greek. The `monotone` test aligner then links the words exactly, so the correct placement is known in advance and every expected score can be worked out by hand. The `none` aligner links nothing, which shows the fallbacks. Positions are counted without spaces and without punctuation.

| Paragraph | What it tests | monotone | none |
|---|---|---|---|
| 1 | `<q>` inside a sentence | placed correctly | fallback (`q:unaligned`) |
| 2 | same, but the gold puts `<q>` one word earlier | 1 of 2 tags right, 5 letters off | fallback |
| 3 | one Greek sentence, two English ones: **grouped** | placed correctly | fallback |
| 4 | a `<note>`: the gold puts it before the next word, the pipeline after the previous one; the same place once spaces are ignored, and its content is not compared | placed correctly | at the sentence end: 5 letters off (punctuation ignored) |
| 5 | two Greek sentences, one English: **whole block** | placed correctly | fallback |
| 6 | a `<label>` (still transliterated by the pipeline; names are translated since 2026-11-20), scored before its replacement by the transliteration | placed correctly | fallback (`label:unaligned`) |
| 7 | no tags inside | `no_tags` | `no_tags` |
| 8 | left in Greek in the gold file | `untranslated` | `untranslated` |
| 9 | a `<milestone>` before the next word | placed correctly | at the sentence end: 5 letters off (punctuation ignored) |

Over the file, `monotone` places 11 of the 12 gold tags exactly. `none` scores only 2 tags (both wrong), and falls back on 5 of the 7 placeable paragraphs, so its strict accuracy over all 12 tags is 0.
