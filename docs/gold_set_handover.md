# Handover: creating the gold translations

For: the agent (Antigravity) that creates the gold translations. Read `CLAUDE.md` first: it describes the repo, the pipeline and the conventions (`pip install -e .[dev]`, `PYTHONUTF8=1` on Windows).

Scope: this document covers **only creating the translations**. How they are later used for testing, and who checks them, is organised separately.

Status: points marked **(confirm)** are still open for the team.

## 1. What the gold set is and why we need it

The gold set is a set of **English TEI files**, each a translation of one Ancient Greek TEI file from Perseus, with **exactly the same tags as the Greek**, placed where they belong in the English. It is the reference our pipeline's output will be compared against.

We need it because nothing in the repo says where a tag *should* go in an English translation:
- our pipeline places the tags automatically (word alignment), and nobody has measured how well;
- the Perseus English translations have different tags (their own notes, `placeName`s the Greek doesn't have, ...) and often follow a different edition, so they can't serve as a tagged reference.

The focus is **correct tag placement**. The translation must be good enough that every tagged Greek word has a clear English equivalent, but the gold set is not used to score translation quality (that is done with the Perseus translations and chrF/BLEU).

## 2. Which texts

**The user tells you which texts to translate**, one or a few at a time. Do not pick texts yourself and do not translate the whole corpus.

For a requested work (e.g. `tlg0059.tlg007`):
- **Greek source:** `data/perseus/texts/<work>/greek/<file>.xml` (the file listed in `data/perseus/pairs.csv`, column `greek_path`).
- **English references:** every file in `data/perseus/texts/<work>/english/` listed for that work in `pairs.csv` (column `english_path`; one row per translation, often more than one).

If `data/perseus/` is missing, download it first: `python scripts/data/build_dataset.py`.

## 3. Where the output goes

All output goes in **`data/gold/grc-en/`** (in the repo and tracked in git, not git-ignored: the gold set is small, hand-made and cannot be re-created by a script; delete the `.gitkeep` once the first file is there).

- **Gold file:** `data/gold/grc-en/<greek file stem>.en.xml`, e.g. `tlg0059.tlg007.perseus-grc2.en.xml` (the same naming as the pipeline's `outputs/<name>.en.xml`).
- **Notes file (optional):** `data/gold/grc-en/<greek file stem>.notes.md` (e.g. `tlg0059.tlg007.perseus-grc2.notes.md`, not `...en.notes.md`; one per gold file) for anything debatable: places where the references disagree with our Greek, unclear tag positions, unusual cases. Don't put such notes in the XML.
- **Index:** `data/gold/grc-en/translations.csv`, one row per gold file:

| Column | Meaning |
|---|---|
| `gold_file` | the `.en.xml` file name |
| `greek_file` | path of the Greek source under `data/perseus/` |
| `english_references` | paths of the English translations used, separated by `;` |
| `translator` | model name and version that produced the translation |
| `date` | date the file was finished (YYYY-MM-DD) |
| `status` | `complete` or `partial` (long texts may take several sessions; say where you stopped in `notes`) |
| `notes` | short remarks; details go in the notes file |

## 4. How to translate

You translate the text yourself, but **not from the Greek alone**. For every passage you look at two sources.

### a) The original Greek TEI: which tags, and where

The Greek file decides the structure of the English file. Your English must have **the same set of tags** as the Greek: the same elements with the same attributes under the same parents. Inside a text block (`<p>`, `<l>`, `<head>`, ...) the order of inline tags may change, because English word order differs ("ὁ Χῖος Ἴων" → "Ion of Chios"). Everything outside the blocks (`div`s, milestones or page breaks between blocks) stays identical and in the same order.

What to do with each element is decided in `config/policy.yaml` (the team's decisions, see `docs/tag_decisions.md`), the same rules our pipeline follows:
- **translate** (`p`, `l`, `head`, `q`, `said`, `quote`, `add`, `del`, `hi`, ...): translate the text, keep the tag around the English words that translate its Greek content.
- **names and numbers are translated too** (since 2026-11-20; `name` of every type, `persName`, `placeName`, `rs`, `num`): write them as a good English translation would and put the tag around them. Names in their usual English form (`<name>Περικλέους</name>` → `<name>Pericles</name>`, `Ἀθηναίοις` → `Athenians`), numbers in English (`<num>δʹ</num>` → `<num>four</num>`, or `<num>4</num>` where English would use digits, e.g. a book number in a reference).
- **keep** (`term`, `foreign`, `bibl`): copy the element unchanged, Greek included, and put it where its Greek words belong in the English sentence.
- **keep-subtree** (`note`): copy byte-for-byte, with everything inside it, after the English of the Greek word it comments on.
- **transliterate** (speaker labels only: `speaker`, `label`): write the content letter by letter in Latin script as `grc_simple` does (`Δεσπότης` → `Despotes`, `ΣΩ.` → `SO.`). This includes elements inside them, even ones whose own rule is translate: `<speaker>Δεσπότης <num>α</num></speaker>` → `<speaker>Despotes <num>a</num></speaker>` (inside a transliterated element the more protective rule wins).
- **empty markers** (`milestone`, `gap`, `pb`, `lb`): copied unchanged. A `milestone` goes before the English of the Greek word that follows it; a `gap` after the English of the Greek word before it; `pb`/`lb` (printed page/line of the Greek) at the nearest sentence boundary. A `milestone` with `unit="para"` goes at the sentence boundary.
- Attributes are always copied unchanged (`n`, `unit`, `who`, `key`, `xml:id`, ...).
- Nested tags stay nested: an inner tag stays inside its outer tag.
- Comments in the Greek file are copied too, at the matching place.

Placing an element with content: put the tags around the **smallest English span that translates the Greek content**. If the English needs words around it that have no Greek counterpart inside the tag (an article, "of"), leave them outside. If the English splits the content into separate pieces, cover all of them with one span and mention it in the notes file.

Placing an empty marker or note: put it directly before the next word, without a space in between (`all, <milestone/>I`, not `all,<milestone/> I`).

Sentences don't have to match the Greek one to one: split or join them as good English needs, as long as every tag can still be placed correctly.

### b) The Perseus English translations: for meaning

Before translating a passage, read the same passage in **all** English references (match them by the citation numbers of the textpart `div`s; `units()` in `scripts/compare_engines.py` does this already and can be reused). Use them to understand the Greek and get the meaning right, and reuse their wording where it fits. Then write your own translation that follows **our Greek text**:
- where the references disagree with each other or with our Greek (they sometimes follow a different edition), follow our Greek and add a remark to the notes file;
- ignore the tags in the English files and do not copy their notes: only the Greek file's tags go into the gold file;
- write faithful, fairly literal English, without your own notes, brackets or comments.

### c) Header and languages (as our pipeline does)

- `teiHeader`: copy unchanged, then add one `respStmt` at the end of `titleStmt`, in the same form the pipeline uses (so the validator accepts it):

  ```xml
  <respStmt>
    <resp>gold translation (grc to en), translator: MODEL NAME AND VERSION, with the Perseus English translations as reference</resp>
    <name>tei-translate</name>
  </respStmt>
  ```
- `xml:lang`: change `grc` to `en` on the elements whose text you translated, but not inside kept elements (`note`, `foreign`, `term`, `bibl`): those stay as they are.

Tip: `python -m tei_translate translate GREEK.xml --engine identity --placement spanwise` writes a copy of the Greek file to `outputs/` with the `respStmt` and the `xml:lang` changes already done and all tags in place. You can start from that copy and replace the Greek text block by block (then edit the `resp` text).

## 5. Verify with the tools, every time

After every block or passage you change, and before saving a file as finished, run the pipeline's validator on the Greek source and your English file and fix every failed check. Write a small script for this, e.g. `scripts/gold/check_gold.py GREEK.xml GOLD.xml`, that:

1. parses both files with `lxml`;
2. calls `tei_translate.pipeline.validate.validate(source_tree, gold_tree, policy, "grc", "en")` with the policy from `tei_translate.pipeline.policy` (`config/policy.yaml`);
3. prints each check (`well-formed`, `same structure`, `@n preserved`, `@xml:id preserved`, `kept elements unchanged`, `header unchanged`) with its detail, and exits with code 1 if one fails;
4. additionally reports, per block, any element that is missing, extra or has changed attributes, and any block where Greek letters remain outside kept elements (something left untranslated), so you can find the problem quickly.

These checks prove that the **right tags are there**; they cannot prove that each tag is in the **right place**. That is your job when translating (section 4a).

For long texts: work section by section, save often, and set `status` to `partial` in `translations.csv` until the whole file is done.

## 6. Open points for the team

1. ~~Names inside transliterated tags: usual English form or our transliteration?~~ Settled for now (2026-11-20): names and numbers are translated (usual English form); only speaker labels are transliterated. If the policy changes again, existing gold files must be updated to match.
2. Commit the gold files as they are produced, or only when a work is complete?
