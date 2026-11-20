# TEI tag decisions

What we do with each TEI tag, and why. ✅ = decided, 🟡 = still to agree.
The rules themselves live in `config/policy.yaml`.

**Scope ✅:** Ancient Greek → English, all 626 Greek files in Perseus
[canonical-greekLit](https://github.com/PerseusDL/canonical-greekLit) that have an English
translation (`data/catalog/greek_english_texts.csv`). Only `<text>` is translated; the
`<teiHeader>` is copied unchanged.

Counts are from the Greek files (`python scripts/data/count_tags.py` →
`data/stats/tei_tag_frequencies.csv`). Tag meanings follow the
[TEI P5 Guidelines](https://tei-c.org/release/doc/tei-p5-doc/en/html/ref-note.html).

## Notes: copied unchanged ✅

`<note>` and everything inside it is copied as it is and stays in place. Notes are editors'
comments, mostly already in Latin (12,149) or English (4,611), and only 1.4% of the text.
Side effect: 99% of `<foreign>` is inside notes, so outside them it's rare (350).

## Containers: kept as they are ✅

`text`, `body`, `div`, `sp`, `lg`, `cit`, `list`, `choice`. They hold other tags, not text, so
they stay correct automatically.

## Empty markers: copied, placed as well as we can 🟡

| Tag | Marks | Count |
|---|---|---|
| `milestone` | section or line number | 66,410 |
| `pb` | page break in the printed edition | 17,772 |
| `lb` | line break | 14,616 |
| `gap` | missing text | 1,864 |
| `figure`, `anchor`, `space`, ... | rare | < 700 |

Many sit in the middle of a sentence, so they need a place in the English. Current setting:
`pb`, `lb` and paragraph milestones go to the nearest sentence boundary; other `milestone`s go
before the English of the next Greek word; `gap` after the English of the previous one. The
checks make sure none are lost or reordered.

## Text blocks: the units we translate ✅

`p` (116,242), `l` (105,139), `head` (1,699), `item`, `stage`: translated.
`speaker` (17,878, e.g. `ΑΘ.`): written in Latin letters.
18% of `<l>` are inside a `<p>` (verse quoted in prose); they're still translated line by line.

## Inline tags 🟡

These wrap a few words inside a sentence, so they have to be placed again after translation.
Counts are outside notes.

| Group | Tags | Count | Proposed | Current setting |
|---|---|---|---|---|
| Speech, quotes | `q`, `said`, `quote` | 41,465 | translate | translate |
| Numbers | `num` | 29,066 | keep | translate |
| Names | `name`, `rs`, `persName`, `placeName` | 23,010 | transliterate | translate |
| Speaker labels | `label` | 14,529 | transliterate | transliterate |
| Editors' corrections | `add`, `del`, `corr`, `sic`, `supplied`, ... | 11,640 | future work | translate |
| References | `bibl` | 5,908 | keep | keep |
| Letters as letters | `term` | 761 | keep | keep |
| Formatting | `hi`, `emph` | 680 | translate | translate |
| Foreign words | `foreign` | 350 | keep | keep |
| Unparsed words | `seg` | 318 | translate | translate |

Names and numbers were switched to "translate" on 2026-11-20 (Ennio, for now): the model gives
the usual English form (*Pericles*, *Athenians*, *four*). Most `num` tags (93%) are point labels
in Euclid (ΑΒ), not numbers. Tags not in the list are translated and reported as unknown.

## Open

- Which inline groups count as "in scope" for the evaluation.
- Names and numbers: keep them translated by the model?
- Where empty markers go (current setting above).
- Editors' corrections: in scope or future work?
