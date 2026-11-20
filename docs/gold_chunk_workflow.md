# Gold translations of long texts: chunks

Long Greek files are split into chunks so several translators can work in parallel. This file
only covers the splitting and joining; what to do with each tag is in
[tag_decisions.md](tag_decisions.md) and `config/policy.yaml`.

## Steps

1. `python scripts/gold/prepare_chunks.py` splits each Greek file into chunks of about 1200 Greek
   words, each with the matching passages of the Perseus English translations (matched by
   citation, so long passages can be approximate). Output: `outputs/gold/chunks/<stem>/NNNN.src.txt`
   and `outputs/gold/manifest.csv`.
2. Write `NNNN.en.txt` next to each `.src.txt`, then run
   `python scripts/gold/check_chunk.py outputs/gold/chunks/<stem>/NNNN.en.txt` until it says `[PASS]`.
3. `python scripts/gold/assemble.py <stem>` puts the English back into the Greek file, fixes
   `xml:lang`, adds the `respStmt`, validates and writes `data/gold/grc-en/<stem>.en.xml`. Then add
   the row to `translations.csv` and the `.notes.md` file.

`python scripts/gold/status.py` shows progress. `--next N --words W --claim` hands out the next
chunks and records them in `outputs/gold/claimed.txt`, so two translators don't get the same one.

## The chunk files

A `.src.txt` has a header, an `## ENGLISH REFERENCE` section and a `## GREEK BLOCKS` section. Each
block starts with a line `=== <index> <ref>`, followed by its XML.

The `.en.txt` has **only** those `=== <index> <ref>` lines, unchanged and in order, each followed
by the English XML of that block. Nothing else.

`check_chunk.py` checks that each block is valid XML, has the same root and attributes, the same
elements under the same parents, markers in the same order, kept elements unchanged, and no Greek
left outside kept elements.

Blocks inside a kept element (e.g. a cast list inside a `<note>`) also show up in chunks;
`assemble.py` keeps their Greek whatever you write.

## Choices made for Thucydides (keep them)

- A sentence that runs into the next block ends the same way in English (`;`, `:` or `,`).
- Verse: each `<l>` holds the English of its own Greek line.
- Editorial brackets (`[...]`, `〈...〉`, `†`) go around the English of their content. A bracketed
  particle with no English equivalent is dropped with its brackets.
- A Greek word discussed as a word is transliterated (*logos*).
- Escape `&`, `<`, `>` in text.
