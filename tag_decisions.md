(this file was written with Claude, but proof read by Ilaria, just helps to keep track of all decisions made)

# TEI tag decisions

This file records which TEI tags our tool handles, how each one is treated, and why.
Every tag found in our data is listed here, so nothing is handled by accident.

**Status:** sections marked ✅ are decided. Sections marked 🟡 are proposals still to be agreed by the team.

## Scope ✅
- **Direction:** Ancient Greek → English only (source: Greek TEI files; reference: their English translations).
- **Data:** Perseus [canonical-greekLit](https://github.com/PerseusDL/canonical-greekLit): 596 works that have both a Greek edition and an English translation (626 Greek files). See `texts/greek_english_texts.csv`.
- **What is counted:** only the `<text>` part of each Greek file. The `<teiHeader>` holds metadata (publisher, licence, editors) and is copied unchanged.

## The three treatments
| Treatment | Meaning | Example |
|---|---|---|
| **translate** | The text is translated into English | `<p>`, `<q>` |
| **keep** | The text is copied exactly as it is | a reference like `Hom. Il. 2.108` |
| **transliterate** | The text is converted to Latin script (or its standard English form) | `<name>Περικλῆς</name>` → `Pericles` |

## How the numbers were found
All counts come from the Greek files and can be reproduced with `python texts/counting_script.py`, which writes `texts/tei_tag_frequencies.csv`. Two measures decide which group a tag belongs to:
- **has text:** the tag has text directly inside it, not only inside its child tags. Containers and empty markers have none.
- **inline share:** how often the tag sits inside a `<p>` (paragraph) or `<l>` (verse line), i.e. in the middle of a sentence. After translation the word order changes, so these tags must be placed again in the English sentence.

Tag meanings follow the TEI P5 Guidelines: `https://tei-c.org/release/doc/tei-p5-doc/en/html/ref-<tag>.html` (e.g. [ref-note.html](https://tei-c.org/release/doc/tei-p5-doc/en/html/ref-note.html)).

---

## 1. Editors' notes: copied unchanged ✅
**Tags:** `note` and everything inside it (mainly `foreign`, `title`, `gloss`, `app`, `lem`, `placeName`, `emph`, and some `bibl` and `hi`).

**What they are:** comments by the modern editor about the Greek text, mostly in Latin (12,149 notes) or English (4,611). Typical example:
`<note xml:lang="lat"><foreign xml:lang="grc">οὔτε] αὐτοὶ</foreign> coni. Apelt.</note>` ("for οὔτε, Apelt suggests αὐτοὶ").

**Treatment:** the whole note, including its content and every tag inside it, is copied unchanged and kept in its original position.

**Why:**
- Notes are not part of the Greek text we translate. They are already in Latin or English, and they comment on the Greek original.
- They are a small part of the data: **1.4%** of all letters in the Greek `<text>` sections (520k of 36.1M). 328 of 626 files contain notes; in no file are notes more than 26% of the text, and only 47 files are above 10%.
- Leaving them out keeps the project to a size that fits a 6-credit course.

**Effect on other tags:** 99% of `foreign` (28,538 of 28,888) is inside notes. Outside notes, `foreign` occurs only 350 times.

## 2. Containers: kept in place ✅
**Tags:** `text`, `body`, `div` (book/chapter/section), `sp` (one speech in a play), `lg` (group of verse lines), `cit` (a quotation plus its reference), `list`, `choice` (a pair of `sic`/`corr` alternatives).

**What they are:** tags that group other tags. They hold no text of their own.

**Treatment:** copied unchanged, with all attributes. Their contents are handled by the tags inside them, so in the output they wrap the English text in exactly the same structure.

**Why:** the pipeline translates the text inside each tag and puts it back in the same place, so containers stay correct automatically. The structural check (same tags and attributes as the input) verifies this.

## 3. Empty markers: copied, placed as close as possible ✅
**Tags:**
| Tag | Marks | In Greek text |
|---|---|---|
| `milestone` | a section or line number | 66,410 |
| `pb` | a page break in the printed edition | 17,772 |
| `lb` | a line break | 14,616 |
| `gap` | text lost or left out | 1,864 |
| `figure` | an image | 502 |
| `anchor`, `delSpan`, `addSpan` | start and end points of a longer deletion or addition | 86 |
| `space` | blank space | 16 |
| `date` | (always empty in our data) | 45 |

**What they are:** tags with no text inside, e.g. `<pb n="V1_2"/>`.

**Treatment:** copied unchanged. No translate/keep rule is needed.

**Why it still matters:** many of them sit in the middle of a paragraph (29,931 `milestone` and 13,306 `pb` are inside a `<p>`). After translation they still need a position in the English sentence. 🟡 Proposal: place them at the nearest sentence or clause boundary, and check in the evaluation that none are lost (same number as in the input).

## 4. Text blocks: the units we translate ✅
**Tags:**
| Tag | What it is | In Greek text | Treatment |
|---|---|---|---|
| `p` | paragraph | 116,242 | translate |
| `l` | verse line | 105,139 | translate |
| `speaker` | speaker name in a play, e.g. `ΑΘ.` | 17,878 | transliterate |
| `head` | heading | 1,699 | translate |
| `item` | list item | 56 | translate |
| `stage` | stage direction | 5 | translate |

**Treatment:** each block is translated as one unit and put back in the same tag.

**Why:** these are the containers of the actual text. They are always handled; they are not part of the tag selection below.

**Note:** 18% of `<l>` sit inside a `<p>`, which is verse quoted inside prose. They are still translated line by line.

## 5. Inline tags: we select the most frequent groups 🟡
These tags sit inside a paragraph or verse line and wrap a few words. They are the hard case for placement and the focus of the tag-handling evaluation.

Tags with the same meaning are grouped and get one rule, so we can cover more tags with little extra work. Counts are outside notes.

| Group | Tags (count) | Total | What they are | Proposed treatment |
|---|---|---|---|---|
| Speech and quotations | `q` (18,115), `said` (15,169), `quote` (8,181) | 41,465 | quoted words, direct speech, quoted verse | translate |
| Numbers | `num` (29,066) | 29,066 | Greek numerals, e.g. `δʹ` (= 4) | keep (or convert to 4) |
| Names | `name` (21,486), `rs` (1,020), `persName` (483), `placeName` (21) | 23,010 | names of people, places and peoples | transliterate |
| Speaker labels | `label` (14,529) | 14,529 | speaker names inside dialogues, e.g. `ΜΟΣΧΙΩΝ.` (12,782 are inside `said`) | transliterate, like `speaker` |
| Editors' corrections | `add` (4,823), `del` (4,447), `corr` (1,944), `sic` (381), `supplied` (40), `surplus` (4), `unclear` (1) | 11,640 | words the editor added, deleted, corrected or reconstructed | translate, keep tag |
| References | `bibl` (5,908) | 5,908 | citations, e.g. `Hom. Il. 2.108` | keep |
| Letters | `term` (761) | 761 | single letters discussed as letters, e.g. `Μ` | keep |
| Formatting | `hi` (675), `emph` (5) | 680 | uppercase, italic, superscript | translate, keep tag |
| Foreign words | `foreign` (350) | 350 | words in another language (mostly Latin) | keep |
| Unparsed words | `seg` (318) | 318 | words the Perseus parser could not analyse | translate as normal text |

**Notes on the groups:**
- `rs` is always `type="nomorph"` in our data: a name the word parser could not analyse. It is the same thing as `name`.
- `name` has a `type`: person (12,424), ethnic (3,561), place (2,305). Ethnic names such as Ἀθηναῖος ("Athenian") should be **translated**, not transliterated. Many famous names also have a standard English form (Ἀθήναιος → Athenaeus, not "Athenaios").
- `said` and `quote` often wrap a whole speech or block of verse, so they behave partly like text blocks.

### Selecting the groups 🟡
**Proposal:** handle the groups that together cover the three treatments and most occurrences:
1. Speech and quotations (translate)
2. Numbers (keep)
3. Names (transliterate)
4. Speaker labels (transliterate)
5. References (keep)
6. Foreign words (keep): rare, but the clearest "keep" case and part of the original motivation for the project

**Editors' corrections** are frequent but are a textual-criticism problem rather than a translation one. Proposal: future work.

### Tags not selected 🟡
Proposal: an inline tag that is not selected is still kept in the output (so the structure check passes), and its text is translated together with the surrounding sentence. Its position in the English sentence is not evaluated.

---

## Open decisions
| Decision | Options |
|---|---|
| Which inline groups are in scope | see "Selecting the groups" |
| `num`: keep Greek numerals or convert to Arabic numbers | keep / convert |
| Names: transliterate, or use the standard English form when one exists | transliterate / English form / both |
| Position of empty markers in translated text | nearest sentence or clause boundary / end of block |
| Editors' corrections in scope | yes / future work |
