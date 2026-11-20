# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A university group project (Essentials of Text and Speech Processing): translate TEI XML documents from Ancient Greek to English while keeping the XML valid and respecting what each tag means. Corpus: Perseus `canonical-greekLit`. The design must stay language-pair agnostic.

**State of the repo:** an end-to-end pipeline exists (hybrid tag placement by default, span-wise as an option), with test engines and Hugging Face MT engines (Opus-MT/Marian, MADLAD-400), plus the Perseus data scripts, corpus/tag statistics, the evaluation metrics and an engine comparison script.

## Key documents (read before planning or coding)

- `docs/HANDOVER.md` — a draft proposal, **not yet reviewed by the team**: treat its "decisions", pipeline, layout, engine choices and milestones as suggestions to discuss, not settled facts. Confirm with the user before relying on any of it.
- `docs/tag_decisions.md` — the team's per-tag decisions with corpus counts (✅ decided, 🟡 still open). Where it disagrees with the `HANDOVER.md` policy table, `tag_decisions.md` reflects team agreement — e.g. it says `<note>` and everything inside it is copied unchanged, whereas HANDOVER proposes language detection. Flag such conflicts rather than silently picking one.
- `docs/feedback_overview.md` — feedback on the proposal and open decisions. `docs/proposed_tasks.md` — who on the team owns what (Ennio: MT model testing; Andjela: texts/tags; Ilaria: evaluation metrics).
- Open questions listed at the end of `HANDOVER.md` (hardware, name convention, `<del>`/`<choice>` defaults, extra features) must be asked, not assumed.

## Repo layout (set up)

Installable package in `src/tei_translate/` (src layout, `pip install -e .[dev]`): `pipeline/` (policy, spans, transliterate, document, validate; hybrid mode: sentences, detag, placement, hybrid), `align/` (`Aligner` protocol, test aligners, `embed.py` = SimAlign-style aligner), `engines/` (`MTEngine` protocol, test engines, `hf.py` = Hugging Face engines), `metrics/` (`fragments.py`, `scores.py`, `translation_scores.py`), `cli.py`, `ui/` (empty placeholder). Entry points live outside the package: `scripts/` (one-off utilities; `scripts/data/` for Perseus data), and later a root `app.py` for Gradio / HF Spaces. Other folders: `config/` (`policy.yaml`, `pairs/grc-en.yaml`), `data/catalog/` + `data/stats/` (tracked CSVs), `data/raw/` + `data/perseus/` (git-ignored downloads), `models/`, `outputs/`, `logs/` (contents git-ignored, `.gitkeep` only), `docs/`, `tests/` (`tests/fixtures/metrics/` = metric test cases, `tests/fixtures/tei/` = pipeline fixtures). Runtime dependencies: `lxml`, `pyyaml`, `sacrebleu` (chrF/BLEU in `metrics/translation_scores.py`); optional extra `mt` = `torch`, `transformers`, `sentencepiece`, `peft` for the model engines. Add each new one when code that needs it lands.

Layout decisions agreed with the user (don't relitigate):
- **src layout, package `tei_translate`**, chosen over a flat package. Everyone runs `pip install -e .[dev]` first; anything that imports `tei_translate` fails with `ModuleNotFoundError` otherwise.
- **Minimal dependencies**: the user chose not to pre-declare planned deps (lxml, gradio, transformers, ...). Add them to `pyproject.toml` together with the code that uses them; heavy ML deps should go in an optional extra so the base install stays light.
- **Entry points live outside the package**: `scripts/` for one-off utilities, a root `app.py` for Gradio (needed by HF Spaces, which runs `app.py` from the repo root). When `app.py` is added, the Space also needs a `requirements.txt` containing `.` so it installs the package. A CLI, if built, goes in `src/tei_translate/cli.py` (`python -m tei_translate ...`).
- Reusable code goes in the package; generated or large files have a fixed git-ignored home (`data/raw`, `data/perseus`, `models`, `outputs`, `logs`). Code writing there should still `mkdir(parents=True, exist_ok=True)`.

Notes on the scripts:
- `scripts/data/` scripts are stdlib-only and resolve paths from the repo root (`Path(__file__).resolve().parents[2]`), so they work from any folder without installing. `build_dataset.py` imports its sibling `make_work_types.py` by plain name (`from make_work_types import ...`), so the two must stay in the same folder.
- Since the move, `build_dataset.py` / `make_work_types.py` were only checked with `--help` (a full run downloads every pair from GitHub). `count_tags.py` and `check_metric_cases.py` were run and give the same results as before (44/44 metric checks passed then, CSVs unchanged; with the translation metrics added it is now 59/59).
- On Windows, printing Greek can raise `UnicodeEncodeError: 'charmap'`: set `PYTHONUTF8=1` (PowerShell: `$env:PYTHONUTF8 = "1"`).

## Pipeline (built)

Agreed with the user:
- **All tag decisions live in `config/policy.yaml`**, mirroring `docs/tag_decisions.md`. Code knows only *roles* (block / container / inline / empty) and *treatments* (translate / keep / transliterate / keep-subtree), never tag names. Each rule may carry `params` (e.g. `speaker: {treatment: transliterate, params: {scheme: simple}}`); unsupported values give a warning. Lookup order: `overrides` (attribute rules, first match) → `tags` → `empty` → `default`.
- **Empty elements are detected per element** (no text, no children) and get the `empty` rule, so `pb`/`lb` aren't listed. A `tags` entry wins over detection: `milestone` and `gap` are listed (`role: empty`) because their placement differs.
- **`<note>` is `keep-subtree`**: copied unchanged and kept in place (tag_decisions wins over HANDOVER's language detection).
- **Names and numbers are translated by the MT model** (user's choice 2026-11-20, "for now"): `num`, `name`, `persName`, `placeName`, `rs` → `translate` (were keep / transliterate; old rules left as comments in `policy.yaml`); `label`/`speaker` still transliterated. 93% of `<num>` are Euclid point labels (ΑΒ), which MADLAD copies with errors (ΒΓΔ → BBD). Own handling, if needed later: names carry their lemma in `@key` (Beta Code, e.g. `*dio/nusos`), so the dictionary form can be transliterated instead of the inflected one (now gives Perikleous, Sokraten). The gold set (`data/gold/`, Lucian) follows the new rules (`docs/gold_set_handover.md` updated; its only `<num>`s are inside `<speaker>`, hence transliterated).
- **Tests use the live `config/policy.yaml`** (user's choice; a frozen test copy was tried and dropped). When the policy changes, update the expected results. Keep/transliterate inline handling is covered by `<label>`, `<term>` and `<foreign>` in `tests/fixtures/tei/handmade.xml` (last `<p>`).
- **Span-wise mode** (`placement: spanwise`; also the per-block fallback of hybrid mode): every text piece is translated where it is, so no element moves. `elem.text` gets the element's treatment, `child.tail` the parent's. Text outside blocks is never touched. Nested inline elements: the more protective treatment wins (keep > transliterate > translate). Mixed nesting is decided per element and counted in the report (`inline-as-block`, `inline-with-blocks`, `block-in-block`, ...).
- No placeholders/masking: the model sees only plain text.
- `document.apply_spans(spans, engine, src, tgt, report)` does the transliterate + one-batch translate + write-back step. Spans may come from several trees, which is how `scripts/compare_spanwise.py` batches many passages.
- Cost of span-wise (`docs/spanwise_cost.md`, MADLAD): prose passages with a mid-sentence cut lose ~0.6 chrF vs translating the whole passage (control without cuts: +0.1), but get visibly broken sentences. Verse (`<l>` translated line by line) loses ~3 chrF. About a third of the prose cuts come from empty markers/notes (`milestone`, `pb`, `note`, `gap`). Over all Perseus Greek, 17% of blocks are cut, and their pieces are 57% of MT segments.

Flow (`pipeline/document.py: translate_document(path, pair, engine=None, policy=None, placement=None, aligner=None) -> Result(tree, report)`): parse → `spans.collect_spans` → [hybrid: `hybrid.run_hybrid` handles its blocks and hands back the remaining spans] → transliterate (`transliterate.grc_simple`) + one batch to `MTEngine.translate(segments, src, tgt)` (`apply_spans`) → write back keeping whitespace → `xml:lang` src→tgt (not inside kept elements) → add a `<respStmt>` in `titleStmt` → `validate.validate` (well-formed; elements outside blocks identical and in order, inside a block the same elements under the same parents (order may change); `@n`/`@xml:id` per (tag, `@unit`) in order for markers and elements outside blocks; kept elements byte-identical; header unchanged). Engines: `identity`, `tag` (wraps output as `[EN:...]`).

### Hybrid placement (default, `placement: hybrid` in `config/pairs/grc-en.yaml`)

Agreed with the user (approach E): tags are removed, whole sentences are translated, every tag is put back by a per-rule strategy in `policy.yaml` params. Only blocks with treatment `translate` and no blocks inside them (`contains-blocks`, e.g. `<l>` in `<p>`) are hybrid; the `<l>` itself is. The rest stays span-wise.
- `detag.py`: block → plain text + anchors. *wrap* = translated element (its text stays, children are anchors); *fixed* = keep/transliterate element whose Greek the model still sees (`mt_input: source`, the user's choice), its aligned English is **replaced** by the element with its own content (transliterated by its usual span); *point* = empty marker, kept subtree (`note`), comment, `mt_input: remove` (`bibl`), element without letters (moved unchanged).
- `sentences.py`: `split_sentences` (same `SENTENCE_END` as `split_for_mt`, which imports it). Each sentence is one engine segment (one batch per document), so sentence boundaries map exactly; English sentences are joined with single spaces (internal whitespace normalised; block lead/trail whitespace kept).
- `placement.py`: tag covering whole sentences → same English sentences (no aligner); wrap/fixed → smallest English span covering all aligned words (fallback if nothing aligns or span > 2×source words + 3); point between sentences stays there (glued side kept); point inside a sentence: `placement: boundary` (nearer sentence edge) or `align` with `anchor: left` (after the English of the previous Greek word: `note`, `bibl`, `gap`) / `right` (before the next: `milestone`). Outer before inner; crossing siblings → fallback; points inside a sibling are moved out; same (tag, unit) markers kept in order; a point with spaces on both sides keeps them.
- Fallback (`fallback` param): `spanwise` (default: the whole block goes span-wise, counted in the report), `boundary` (points), `sentence` (wraps). Current policy: `empty` → boundary (pb, lb); `milestone` → align/right/fallback boundary, but `milestone[unit=para]` → boundary (97% already at sentence ends); `gap`, `note`, `bibl` → align/left/fallback boundary; other inline tags → align/spanwise. Corpus check (all 626 Greek files, identity engine + `monotone` aligner = exact links): no errors, all checks pass, 217,573 blocks hybrid, 2,928 span-wise (2,862 contains-blocks, ~64 overlaps from tags inside words).
- Aligners (`align/`, registry `get_aligner`): `none`, `monotone` (tests), `ugarit` (`UGARIT/grc-alignment`, XLM-R base 1.1 GB, CC BY 4.0, IterMax), `dragoman` (`open-greek/dragoman`, CC BY 4.0, ArgMax), `xlmr`, `embed:<HF id>`. `EmbeddingAligner`: layer 8 subword vectors, cosine similarity, SimAlign ArgMax/IterMax, word link if any subword pair links; >510 subwords → no links. UGARIT ships only the old sentencepiece file, which Transformers 5 converts only with protobuf, so its tokenizer is loaded from `FacebookAI/xlm-roberta-base` (identical file, checked by sha256). Loads in a few seconds on CPU, ~0.2 s per sentence pair.
- Report: `placement: hybrid, aligner: ...; N blocks placed (sentences translated / aligned), M blocks span-wise`, `tags placed:` counts (aligned, whole-sentence, between-sentences, boundary, fallback-*, clamped, moved-out, kept-in-order), `span-wise because:` reasons (`<tag>:unaligned|too-wide|overlap|outside-parent`, `contains-blocks`).
- chrF hybrid vs span-wise (`compare_spanwise.py` condition `hybrid`, `--aligner`, `--every K` keeps every K-th passage, `--reuse` also takes an `outputs/spanwise/` run): pivot on 16 cut prose passages, hybrid 21.9 vs span-wise 21.6 vs whole 21.7 (within noise; hybrid fixes the broken sentences, 13 of 17 blocks placed, `<add>` fails to align). See `docs/spanwise_cost.md`.
- Not done: a hand-tagged gold set for `metrics.scores.tag_accuracy` on hybrid output, name lists (only relevant if names go back to transliteration).

## MT engines (`engines/hf.py`, registry in `engines/__init__.py`)

- Names: `opus-grk-en`, `opus-bible-ine` (`Helsinki-NLP/opus-mt-tc-bible-big-ine-deu_eng_nld`), `madlad-3b`, `pivot-grc-el-en` (= `nllb-ag-mg` then `opus-el-en`); any model via `marian:<HF id>` / `madlad:<HF id>`. `engine.name` is the HF model id (goes into the respStmt); a chain's name is `first -> second`.
- `engines/chain.py: ChainEngine(first, second, pivot)` runs src→pivot→tgt and keeps the pivot text in `last_intermediate`. `NllbLoraEngine` (ILSP `ilsp/nllb-200-600M-ag-mg-lora`, CC BY-NC): tokenizer from the adapter repo (148 added polytonic chars), base `facebook/nllb-200-distilled-600M` resized, adapter merged; `ell_Grek` on both sides (`forced_bos_token_id`), so it only accepts tgt `el`. The adapter repo is ~2 GB and the base downloads both .bin and .safetensors (~4.6 GB).
- `HFSeq2SeqEngine` base: lazy import of torch/transformers on first `translate()` (pipeline works without the extra); models cached in `models/hf/` unless `HF_HOME`/`HF_HUB_CACHE` is set; GPU used if available. Each segment is split into sentences (`split_for_mt`: `. ! ? ;` and U+037E; over-long sentences at `, : ·` then words, measured in tokens), pieces deduplicated, translated in length-sorted batches (beam 4), joined with spaces.
- `MarianEngine` finds a `>>eng<<`-style target token from the vocab (ISO 639-1 → 639-3 map) or takes `target_token`; single-target models get no prefix. `MadladEngine` prefixes `<2en>` and runs in bfloat16 on GPU and CPU (fp32 is 12 GB; T5 overflows in fp16; `cpu_float32=True` for full precision). On the user's laptop (Ryzen 7 250, 30 GB RAM, no GPU) it loads in ~25 s and translates ~5.5 Greek words/s, about as fast as `pivot-grc-el-en`. Weights: one 11.8 GB model.safetensors (the repo's .gguf files are not used).
- Generation uses each model's defaults (no repetition penalty); Opus models loop on input they don't understand (e.g. Homer).
- `tie_output_embeddings` (called only in `MarianEngine._load`): Transformers 5 no longer ties `lm_head` to the embeddings when a checkpoint stores both with different values; `opus-mt-tc-big-el-en` then outputs random words. Do NOT make it generic: Transformers 5 reports `tie_word_embeddings=True` even for MADLAD, whose config.json says false and whose separate `lm_head` is real (forcing the tie gave garbage). If a new model outputs word salad even on easy input (check with "Καλημέρα, πώς είσαι;"), check its lm_head/embedding tying first.
- Current ranking (54 passages, `docs/engine_comparison.md`): `madlad-3b` chrF 31.5 ≥ `pivot-grc-el-en` 30.4 >> `opus-bible-ine` 23.7 ≈ `opus-grk-en` 22.6. The top two are close; most chain errors come from step 1 (NLLB).
- **Default engine: `madlad-3b`** (user's decision 2026-11-20, locally and on the HF Space; `engine:` in `config/pairs/grc-en.yaml`). `pivot-grc-el-en` is the fallback if MADLAD is too slow on the Space CPU or the team fine-tunes (reasons in `docs/engine_comparison.md`, "Decision"). So a run without `--engine` needs the `mt` extra and the 11.8 GB model; tests and quick checks should pass `--engine identity`/`tag` explicitly.
- `scripts/compare_engines.py` (`--reuse RUN_DIR` reuses an earlier run's passages/translations and only runs new engines; writes `run.json` with models/timings): plain-text bake-off on Perseus prose sections + Pindar odes aligned by citation ref (leaf textpart divs; notes/bibl/head/reg removed — `<reg>` holds gazetteer text in some English files), corpus chrF/BLEU overall and per work → `outputs/compare/<timestamp>/`. Results (Opus models, pivot chain, MADLAD): `docs/engine_comparison.md`. `--subset N` / `--max-words W` (with `--reuse`) score all engines on a smaller subset, for slow engines.
- `scripts/bench_engine_threads.py ENGINE THREADS RUN_DIR [--every K] [--aligner ugarit]`: speed and peak memory (Windows counters) with limited CPU threads, on a compare run's passages; one engine per process. With 2 threads (like the free HF Space): pivot 2.0 words/s, MADLAD 1.75; peak committed memory 9.2 GB / 11.9 GB, both under 16 GB. Untested: the Space CPU's bfloat16 speed. See `docs/engine_comparison.md`.

Later (HANDOVER ideas, not agreed): placeholders, real engines after the bake-off, tei_all validation, name lists for standard English forms.

Core invariant: **the MT model never sees XML structure**; structure is never generated by a model.

## Frontend / deployment (decided)

The UI is a Gradio app (one Python codebase with the pipeline). The same app runs locally (`python app.py`, opens in the browser) and is deployed for free on Hugging Face Spaces (CPU-only free tier, so it must work with a CPU-friendly model), with code kept on GitHub. Optional: a static GitHub Pages showcase of precomputed example translations.

Why and what follows from it:
- GitHub Pages is static-only and can't run Python or models, so the hosted app lives on HF Spaces. Code stays on GitHub; a GitHub Action can sync it to the Space. Fine-tuned models can be hosted on the HF Hub.
- The local UI is meant to be easier than the terminal for non-technical users, so the pipeline should be callable as a library: Gradio and the CLI are thin layers over the same functions.
- Local runs can use a GPU and bigger models (e.g. MADLAD 3B). The Space can't, so the engine must be selectable by config. The Space sleeps when idle and suits passages, not whole works.
- `demo.launch(share=True)` gives a temporary public link to a local run, useful for team demos.
- Local users still need to install Python, the dependencies and model downloads, so aim for a single install command and a clear README.

## Planning status

Done: project skeleton, span-wise pipeline with test engines and validation, hybrid tag placement with word aligners (UGARIT), Opus-MT/MADLAD/NLLB-LoRA engine wrappers, the `pivot-grc-el-en` chain, and a comparison of the Opus models and the chain. Still open:
- The user raised "which languages to use and how to present them" in the UI. Settle this: which source/target language pairs to offer, and how language and option choices appear in the UI.
- The open questions at the end of `HANDOVER.md`. (Engine choice: settled, MADLAD by default.)

## Commands

Python 3.10+ on Windows (user has 3.14, CPU only). `pip` may not be on PATH: use `python -m pip` / `python -m pytest`. Dependencies (`lxml`, `pyyaml`, `sacrebleu`) are installed by `pip install -e .`; model engines need `pip install -e .[mt]`.

```
pip install -e .[dev]                    # install the package (editable) + pytest
python scripts/data/count_tags.py        # clones Perseus into data/raw/canonical-greekLit/ on first run, writes data/catalog/*.csv and data/stats/tei_tag_frequencies.csv
python scripts/data/build_dataset.py     # downloads Greek/English pairs into data/perseus/, classifies works (poetry/prose/drama)
python scripts/data/count_perseus_tags.py  # tag counts over data/perseus/ (needs build_dataset.py first): data/stats/perseus_tag_frequencies_{greek,all}.csv
python scripts/check_metric_cases.py     # runs the tag-placement, structure and translation metrics on tests/fixtures/metrics/*.json, prints PASS/FAIL per case
python -m tei_translate translate IN.xml --engine tag   # writes outputs/<name>.en.xml, prints rules fired + validation; exit 1 if a check fails
python -m tei_translate translate IN.xml --engine opus-grk-en --aligner ugarit   # hybrid (default); --placement spanwise for the old mode, --aligner none|monotone without a model
python scripts/compare_engines.py --engines opus-grk-en opus-bible-ine   # MT bake-off on Perseus passages -> outputs/compare/
python scripts/compare_spanwise.py --engine madlad-3b [--reuse outputs/compare/<run>] [--every 2] [--aligner ugarit]   # whole vs split vs span-wise vs hybrid on the same passages -> outputs/spanwise/
```

`python -m pytest` runs the suite: `tests/test_metrics.py` (one test per hand-made metric case in `tests/fixtures/metrics/`), `tests/test_policy.py` and `tests/test_pipeline.py` (span-wise pipeline, on `tests/fixtures/tei/`), `tests/test_placement.py` (hybrid: identity+monotone, a word-reversing engine + exact-match aligner, single blocks with hand-made links), `tests/test_align.py` (tokenizer, sentences, ArgMax/IterMax), `tests/test_engines.py` (registry, splitting, prefixes); real-model tests only with `TEI_TRANSLATE_RUN_MODELS=1`. `python -m pytest tests/test_pipeline.py::test_names` runs one test. `scripts/check_metric_cases.py` runs the metric cases with longer failure explanations.

## Existing assets worth reusing

- `data/catalog/greek_english_pairs.csv` / `greek_english_texts.csv` — every Greek file in Perseus that has an English translation, with paths; useful for the data loader. Perseus file naming (paths inside the Perseus repo, i.e. under `data/raw/canonical-greekLit/`): `data/TEXTGROUP/WORK/TEXTGROUP.WORK.perseus-{grc,eng}N.xml`; prefer higher `N` (version 1 files are often not CTS-compliant).
- `data/stats/tei_tag_frequencies.csv` — per-tag counts inside `<text>` (Greek vs English), basis for `tag_decisions.md`.
- `src/tei_translate/metrics/scores.py` (import as `tei_translate.metrics.scores`) + `tests/fixtures/metrics/` — verified implementation of tag accuracy and average distance (positions = character offsets in tag-stripped text; requires identical text in reference and hypothesis) plus XML accuracy / XML matching. `src/tei_translate/metrics/translation_scores.py` — corpus-level chrF and BLEU via sacrebleu, tags removed with `fragments.strip_tags` (best effort for broken XML), several references per passage allowed.
