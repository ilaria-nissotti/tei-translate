# Test items for the tag-placement evaluation

`gold.jsonl` holds five hand-made gold items, used by `tests/test_placement_eval.py` to test `src/tei_translate/metrics/placement_eval.py` (and to try `scripts/eval_placement.py` without the real gold set). They follow the gold-item format of `docs/gold_set_handover.md`. They are **not** part of the gold set, which lives in `data/gold/grc-en/`.

Each English sentence has the same words in the same order as its Greek sentence. The `monotone` test aligner then links the words exactly, so the correct placement is known in advance and every expected score can be worked out by hand. The `none` aligner links nothing, which shows the fallbacks.

| Item | What it tests | monotone | none |
|---|---|---|---|
| `test:q_right` | a wrap element (`<q>`) inside a sentence | placed correctly (1.0) | fallback (`q:unaligned`) |
| `test:q_gold_wider` | same block, but the gold puts `<q>` one word earlier | 1 of 2 tags right (0.5), average distance 3 | fallback |
| `test:name_fixed` | a fixed element (`<name>`), scored before its replacement by the transliteration | placed correctly (1.0) | fallback (`name:unaligned`) |
| `test:milestone` | a point element (`placement: align`, `anchor: right`) | placed correctly (1.0) | placed at the sentence end by its fallback: 6 characters off |
| `test:split_mismatch` | the gold lists one Greek sentence, the pipeline splits the block into two | reported as `split_mismatch`, not scored | the same |

Over all items, `monotone` places 6 of the 7 gold tags exactly (85.7%), and `none` falls back on 3 of the 5 items (60%).
