# Handover: building the tag-placement gold set

For: the agent (Antigravity) that builds the gold set. Read `CLAUDE.md` first: it describes the repo, the pipeline and the conventions (src layout, `pip install -e .[dev]`, `PYTHONUTF8=1` on Windows, minimal dependencies).

Status: proposal. Points marked **(confirm)** must be agreed with the team before they are built on.

## 1. Why we need a gold set

The hybrid pipeline (the default) removes the tags from a block, translates whole sentences and puts every tag back into the English text with a word aligner (`pipeline/detag.py`, `placement.py`, `hybrid.py`). Right now **nobody has measured how well it places the tags.**

What we have:
- `metrics/scores.py`: `tag_accuracy` and `average_distance` (Zenkel et al. 2021), checked on the hand-made cases in `tests/fixtures/metrics/cases.json`.
- A corpus run over all 626 Greek files with the `identity` engine and the `monotone` aligner. That only shows that the code never crashes and that the XML stays valid. The links are exact by construction, so it says nothing about placement quality.
- chrF/BLEU against the Perseus English translations (`scripts/compare_engines.py`). These measure **translation**, and `strip_tags` removes the tags first, so they say nothing about tags.

What is missing: a reference that says where each tag **should** go in a real English translation. Without it we cannot answer the questions the project depends on:
- Which aligner places tags best: `ugarit`, `dragoman`, `xlmr`, or the no-model baselines (`monotone`, `none` = fallbacks only)?
- Are the per-tag placement params in `config/policy.yaml` right? For example `anchor: left` vs `right` for `note`/`milestone`, `boundary` vs `align` for `milestone`, and the `fallback` choices.
- How often does a block fall back to span-wise, and for which tags?
- Which tag types fail (the `per_tag` field of `scores.score`)?

`CLAUDE.md` lists this as not done: "a hand-tagged gold set for `metrics.scores.tag_accuracy` on hybrid output". `HANDOVER.md` plans the same thing ("Projection accuracy: Zenkel et al. metrics on a small hand-tagged set; fallback rate per document").

### Why the metric needs a special kind of gold set

`tag_accuracy` and `average_distance` compare **character positions**. They only work when the reference and the output have **exactly the same text** once the tags are removed. Otherwise `score()` returns `same_text: False` and all placement scores are `None` (see `tests/fixtures/metrics/README.md`).

So:
- **The Perseus English files cannot be used as the scored text directly** (they are still used as translation aids, see Step 2). Their wording is different from any MT output, they are not sentence-aligned with the Greek, they sometimes follow a different edition, and they have their own tags (e.g. a `<placeName>` the Greek has no equivalent for).
- **The English text must be fixed** in the gold set, and the pipeline must be made to produce exactly that text. Then only the tag positions can differ, and the metric compares those.

## 2. The two points to confirm

### "A frontier model translation is probably the best translation we can get" — confirmed, with limits

For **this** purpose, yes. The gold set needs a fixed English text that:
1. is a faithful, fairly literal translation, so that every tagged Greek word has a clear English equivalent. Our own engines are too weak for that: the best one, `madlad-3b`, reaches only chrF 31.5 (`docs/engine_comparison.md`), and on poetry it often produces nonsense. Where no English corresponds to a tagged Greek word, there is no correct place for the tag, and the case only measures noise;
2. has **exactly one English sentence per Greek sentence**, as the pipeline splits them (`pipeline/sentences.py: split_sentences`). The hybrid pipeline sends each sentence to the engine as one segment and joins the results with single spaces. A frontier model (GPT/Gemini/Claude class) can be instructed to keep that 1:1 mapping; the Perseus translations cannot.

The frontier model does **not** translate the Ancient Greek on its own. It works from two sources at once (details in Step 2):
- the **original Greek TEI block**, which tells it which tags there are and where they sit, so it can place them in its English; it verifies with a tool that its output has the same set of tags;
- the **Perseus English translations** of the same passage (there may be several per text), which it uses as a reference to get the meaning right. It rewrites them into one English sentence per Greek sentence rather than translating from scratch.

Limits, to state in the report:
- "Best we can get" means best available to us, not perfect. A frontier model still makes mistakes in Ancient Greek, so **a person who reads Greek has to check every sentence** (a quick check is enough; we need a usable translation, not a polished one).
- The gold set does **not** measure translation quality, and the frontier translation is not used as an MT reference. For translation quality we keep using the Perseus human translations with chrF/BLEU.
- Record the model name, version and date, and the prompt, so the set is reproducible. Check that the model's terms allow this use.

### "This gold set focuses more on correct tag placement" — confirmed

Yes, it is **only** about tag placement. The English text is fixed, so translation quality is held constant on purpose: every system is scored on the same English, and the difference in score comes only from where the tags end up. This isolates the aligner and the placement rules from the MT engine.

Consequences:
- It scores **hybrid** placement. Span-wise mode translates each piece separately, so its English text differs and cannot be scored with these metrics (the cost of span-wise is measured separately in `docs/spanwise_cost.md`).
- A block that falls back to span-wise has no placement score. Count it as a fallback and report the fallback rate next to the accuracy.
- Structure (XML well-formed, same tags as the input) is already checked by `pipeline/validate.py` and by `xml_accuracy`/`xml_matching`; no gold set is needed for it.

## 3. What a gold item looks like

One item = one hybrid block (`<p>`, `<l>`, `<head>`, ... with treatment `translate` and no block inside it) from a Greek file in `data/perseus/texts/*/greek/`. Proposed format: one JSON object per line in `data/gold/grc-en/gold.jsonl` **(confirm format)**.

**Location (decided):** the gold set lives in the repo, in `data/gold/grc-en/`. The folder exists and is tracked in git (it holds only a `.gitkeep` for now; delete that once real files are added). Unlike `data/raw/` and `data/perseus/` it is **not** git-ignored, because the gold set is small and hand-checked and cannot be re-created by a script. Put everything that belongs to the set there: `gold.jsonl`, `GUIDELINES.md`, the sample selection from Step 1, and the prompt used in Step 2. The `grc-en` subfolder keeps the layout language-pair agnostic, so a later pair gets its own folder next to it. Scripts that write there should still `mkdir(parents=True, exist_ok=True)`.

| Field | Meaning |
|---|---|
| `id` | e.g. `tlg0003.tlg001:1.1.1:p0` (work, citation of the enclosing `div`s, block index) |
| `file` | path under `data/perseus/` |
| `xpath` | where the block is in the file, so it can be found again |
| `type` | prose / poetry / drama (from `data/perseus/work_types.csv`) |
| `greek_block` | the Greek block as XML, copied from the file |
| `greek_sentences` | the block's plain text split with `split_sentences`, exactly as the pipeline does it (do not split by hand) |
| `english_references` | the Perseus English translations of the same citation unit (one entry per translation file: path + plain text) that the model was given |
| `english_sentences` | one English sentence per Greek sentence, same length list |
| `english_text` | `" ".join(english_sentences)`: the fixed text all systems are scored on |
| `gold` | `english_text` with the block's tags placed by hand (XML fragment) |
| `translation_source` | model name + version + date, or `human` |
| `annotator`, `checked_by` | who (which model) placed the tags / which person checked them |
| `notes` | anything debatable |

## 4. How to build it

### Step 1: sample the blocks (script)

Write `scripts/gold/sample_blocks.py` (reuse the package; don't re-implement parsing):
- Read `data/perseus/pairs.csv` / the Greek files in `data/perseus/texts/` (download them first with `python scripts/data/build_dataset.py` if missing).
- Keep only blocks the hybrid pipeline handles: reuse `spans.collect_spans` and `hybrid.group_spans` with the real policy (`config/policy.yaml`), so the selection matches what the pipeline does.
- Keep only blocks that contain at least one tag **inside a sentence**: a block whose tags all sit at sentence edges is placed without any aligner and tests nothing.
- Stratify:
  - by tag type, with a minimum per type: the frequent inline tags (`name`, `foreign`, `num`, `q`, `said`, `label`, `quote`, `note`, `bibl`, `add`/`del`, `milestone`, `gap`); see `data/stats/perseus_tag_frequencies_greek.csv`;
  - by text type (prose, poetry, drama) and across authors, not just Plato and Thucydides;
  - by tag kind: *wrap* (translated element), *fixed* (kept/transliterated element, e.g. `name`), *point* (empty marker, `note`, `bibl`).
- Keep only blocks whose citation unit has **at least one English translation** in Perseus (`data/perseus/pairs.csv` lists every English file per work, often more than one). The English is matched by citation ref, as `units()` in `scripts/compare_engines.py` already does for leaf textpart `div`s; reuse that (move it into the package if needed). Store every matching translation with the item.
- Fixed random seed; write the selection to a file so it can be re-run.
- Skip blocks over ~150 Greek words (annotation cost) and blocks the `ugarit` aligner can't handle (>510 subwords per sentence).

Suggested size **(confirm)**: a pilot of ~20 blocks to test the guidelines, then ~150–250 blocks with ~500–1000 tags in total. Exact-position accuracy needs a few dozen tags per type before per-type numbers mean anything.

### Step 2: translate and place the tags (frontier model, with tools)

The frontier model produces the gold translation **and** places the tags in it, in one step. For each block it must look at two things:

**a) The original Greek TEI block: which tags, and where.**
- Input: `greek_block` (the XML, with all its tags) and `greek_sentences` (the split the pipeline uses), plus the sentences before and after for context.
- The tags in the Greek tell the model which tags its English must contain and where they belong: each tag goes around (or next to) the English words that translate the Greek words it marks in the source, following the rules in Step 3.
- **During translation the model verifies its output with a tool**, and fixes it until the check passes:
  - `metrics.scores.is_valid_xml(gold)`: the English is well-formed XML;
  - `metrics.scores.same_structure(greek_block, gold)`: exactly the same set of tags as the Greek, same attributes, same nesting. The order of tags under the same parent may change (English word order differs: "ὁ Χῖος Ἴων" → "Ion of Chios"), and `same_structure` already allows that;
  - the number of English sentences equals the number of Greek sentences.
  Wrap these in a small checker script (e.g. `scripts/gold/check_item.py ITEM`) that the agent runs after every item and that prints what is wrong (missing tag, extra tag, changed attribute, sentence count). Items that don't pass are not saved.
- Attributes are copied unchanged (`n`, `unit`, `who`, `key`, ...); kept subtrees such as `<note>` are copied byte-for-byte.

**b) The Perseus English translations: for meaning, not to copy blindly.**
- Input: every English translation of the same citation unit (`english_references`; there may be several, e.g. three for Thucydides 1.1.1).
- The model does **not** translate the Ancient Greek on its own. It reads the human translations to understand the passage and to get the meaning right, then writes a version that follows the Greek sentence by sentence (one English sentence per Greek sentence, same order). It may reuse wording from the references where that fits the 1:1 split.
- Where the references disagree with each other or with our Greek text (they sometimes follow a different edition), follow **our Greek** and add a note to the item.
- Ignore the tags in the English files: they are not the tags of our Greek.

Rules for the output:
- Faithful, fairly literal English; no notes, brackets or comments of its own; no merged or split sentences.
- The model never sees our pipeline's output or our aligners' links, so the gold stays independent of the system it judges.
- Names: use the standard English forms (Pericles, not Perikles) **(confirm)**. This doesn't affect scoring of wrap/point tags, but see the fixed-element issue below.
- The model returns `english_sentences` and `gold`; the checker also verifies that `metrics.fragments.strip_tags(gold)` equals `" ".join(english_sentences)` (= `english_text`), so the text and the tags can't drift apart.
- Record the model, version, date and prompt in `translation_source`.

### Step 3: human check

**A person who reads Greek checks every item**: the translation (correct only what is wrong) and every tag position. The tool check in Step 2 only proves that the right tags are present, not that they are in the right place. Write the guidelines down in `data/gold/grc-en/GUIDELINES.md`, give them to the model in its prompt, and extend them after the pilot. Starting rules:
- **Wrap elements** (`q`, `said`, `quote`, `foreign`, `add`, `del`, `hi`, `name[type=ethnic]`, ...): the smallest English span that translates the Greek content. Decide once whether articles and prepositions the English needs are inside (proposal: inside if they translate a Greek word inside the tag, outside otherwise). If the English splits the content into non-contiguous pieces, take the smallest span covering all of them (this is what the pipeline does too) and add a note.
- **Fixed elements** (`name`, `persName`, `placeName`, `label`, `num`, `term`, `rs`): mark the English words that translate them (e.g. `<name>Pericles</name>`). See the caveat below.
- **Point elements**: `milestone` before the English of the Greek word that follows it; `note`, `bibl`, `gap` after the English of the Greek word before it. If the English word order makes that ambiguous, choose the place a reader citing the passage would expect and add a note.
- **`pb`/`lb`**: no correct place in the English exists (they mark the printed Greek page/line). They must still be present (the structure check requires them), but leave them out of the scored tags, or mark them as unscored **(confirm)**.
- Nested tags: the inner tag must stay inside the outer one.
- Whitespace: by the current metric rules a point on the other side of a space counts as 1 character off (`cases.json` case 15). Place points directly before the next word (`, <milestone/>I`), and decide with the team whether the metric should ignore whitespace.

Ideally two people check the pilot independently and their agreement (tag accuracy of one against the other) is reported: it is the ceiling for any system.

### Step 4: evaluation script

Write `scripts/eval_placement.py` (owner of the metrics: Ilaria; coordinate):
- A **replay engine** (e.g. `engines/replay.py`, `ReplayEngine(mapping)`): returns the gold `english_sentences` for the Greek sentences it receives. This makes the pipeline produce exactly `english_text`, so `same_text` is true. It raises if a sentence is not in the gold (that would mean the splitting changed).
- Run the hybrid pipeline on each gold block for every aligner (`ugarit`, `dragoman`, `xlmr`, `monotone`, `none`), and optionally for policy variants.
- Score each block with `metrics.scores.score(gold, output_block)`; report overall `tag_accuracy`, `average_distance`, `per_tag`, missing/extra, and the fallback rate (blocks that went span-wise, from the hybrid report), split by tag kind and text type. Write to `outputs/eval_placement/<timestamp>/`.

#### Caveat: fixed elements change the text

For fixed elements (`name`, `label`, `num`, ...), `placement.rebuild` **replaces** the aligned English words by the element with its own content, which is later transliterated (`Pericles` → `<name>Perikles</name>`). The output text then depends on which words the aligner chose, so when it chooses wrongly the texts differ and `score()` returns `None` for the whole block.

Proposed fix **(confirm)**: an evaluation mode that scores the placement **before** the replacement, i.e. treats fixed elements like wrap elements around the English words they were aligned to (the `Placed` start/end in `layout.english`). The gold then marks the English words the element replaces. The replacement itself is deterministic and does not need a gold set. This needs a small hook in `pipeline/hybrid.py` (e.g. a flag that keeps the `Placed` list or rebuilds fixed anchors as wraps); keep it out of the normal path.

## 5. Pitfalls

- Keep the Greek sentence split identical to the pipeline: always produce `greek_sentences` with `split_sentences` on the detagged text, and re-check after any change to `sentences.py`.
- The `ugarit` and `dragoman` aligners need `pip install -e .[mt]` and download ~1 GB; they run on CPU (~0.2 s per sentence pair).
- Licences: Perseus texts are CC BY-SA, the UGARIT/dragoman models CC BY 4.0. Mention the frontier model and its terms in the report.
- Don't change `config/policy.yaml` while building the gold set; the set should judge the policy, not be fitted to it. Tune params on a separate dev part (e.g. split the set 50/50) **(confirm)**.

## 6. Open questions for the team

1. Format of the gold files (`gold.jsonl` proposed; the folder `data/gold/grc-en/` is decided, for now in the repo).
2. Size: pilot ~20 blocks, then 150–250?
3. Who checks the translations and the tags (someone who reads Greek; Andjela owns texts/tags, Ilaria the metrics, Ennio the MT models)?
4. Which frontier model, and are its terms OK for this use?
5. `pb`/`lb`: unscored or scored?
6. Should the metric ignore whitespace around point tags (case 15)?
7. Fixed elements: score before replacement, as proposed?
8. Dev/test split for tuning the policy params?
