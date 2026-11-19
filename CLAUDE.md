# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A university group project (Essentials of Text and Speech Processing): translate TEI XML documents from Ancient Greek to English while keeping the XML valid and respecting what each tag means. Corpus: Perseus `canonical-greekLit`. The design must stay language-pair agnostic.

**State of the repo:** a first end-to-end pipeline exists (span-wise translation), with test engines and Hugging Face MT engines (Opus-MT/Marian, MADLAD-400), plus the Perseus data scripts, corpus/tag statistics, the evaluation metrics and an engine comparison script.

## Key documents (read before planning or coding)

- `docs/HANDOVER.md` — a draft proposal, **not yet reviewed by the team**: treat its "decisions", pipeline, layout, engine choices and milestones as suggestions to discuss, not settled facts. Confirm with the user before relying on any of it.
- `docs/tag_decisions.md` — the team's per-tag decisions with corpus counts (✅ decided, 🟡 still open). Where it disagrees with the `HANDOVER.md` policy table, `tag_decisions.md` reflects team agreement — e.g. it says `<note>` and everything inside it is copied unchanged, whereas HANDOVER proposes language detection. Flag such conflicts rather than silently picking one.
- `docs/feedback_overview.md` — feedback on the proposal and open decisions. `docs/proposed_tasks.md` — who on the team owns what (Ennio: MT model testing; Andjela: texts/tags; Ilaria: evaluation metrics).
- Open questions listed at the end of `HANDOVER.md` (hardware, name convention, `<del>`/`<choice>` defaults, extra features) must be asked, not assumed.

## Repo layout (set up)

Installable package in `src/tei_translate/` (src layout, `pip install -e .[dev]`): `pipeline/` (policy, spans, transliterate, document, validate), `engines/` (`MTEngine` protocol, test engines, `hf.py` = Hugging Face engines), `metrics/` (`fragments.py`, `scores.py`, `translation_scores.py`), `cli.py`, `ui/` (empty placeholder). Entry points live outside the package: `scripts/` (one-off utilities; `scripts/data/` for Perseus data), and later a root `app.py` for Gradio / HF Spaces. Other folders: `config/` (`policy.yaml`, `pairs/grc-en.yaml`), `data/catalog/` + `data/stats/` (tracked CSVs), `data/raw/` + `data/perseus/` (git-ignored downloads), `models/`, `outputs/`, `logs/` (contents git-ignored, `.gitkeep` only), `docs/`, `tests/` (`tests/fixtures/metrics/` = metric test cases, `tests/fixtures/tei/` = pipeline fixtures). Runtime dependencies: `lxml`, `pyyaml`, `sacrebleu` (chrF/BLEU in `metrics/translation_scores.py`); optional extra `mt` = `torch`, `transformers`, `sentencepiece`, `peft` for the model engines. Add each new one when code that needs it lands.

Layout decisions agreed with the user (don't relitigate):
- **src layout, package `tei_translate`**, chosen over a flat package. Everyone runs `pip install -e .[dev]` first; anything that imports `tei_translate` fails with `ModuleNotFoundError` otherwise.
- **Minimal dependencies**: the user chose not to pre-declare planned deps (lxml, gradio, transformers, ...). Add them to `pyproject.toml` together with the code that uses them; heavy ML deps should go in an optional extra so the base install stays light.
- **Entry points live outside the package**: `scripts/` for one-off utilities, a root `app.py` for Gradio (needed by HF Spaces, which runs `app.py` from the repo root). When `app.py` is added, the Space also needs a `requirements.txt` containing `.` so it installs the package. A CLI, if built, goes in `src/tei_translate/cli.py` (`python -m tei_translate ...`).
- Reusable code goes in the package; generated or large files have a fixed git-ignored home (`data/raw`, `data/perseus`, `models`, `outputs`, `logs`). Code writing there should still `mkdir(parents=True, exist_ok=True)`.

Notes on the scripts:
- `scripts/data/` scripts are stdlib-only and resolve paths from the repo root (`Path(__file__).resolve().parents[2]`), so they work from any folder without installing. `build_dataset.py` imports its sibling `make_work_types.py` by plain name (`from make_work_types import ...`), so the two must stay in the same folder.
- Since the move, `build_dataset.py` / `make_work_types.py` were only checked with `--help` (a full run downloads every pair from GitHub). `count_tags.py` and `check_metric_cases.py` were run and give the same results as before (44/44 metric checks passed then, CSVs unchanged; with the translation metrics added it is now 59/59).
- On Windows, printing Greek can raise `UnicodeEncodeError: 'charmap'`: set `PYTHONUTF8=1` (PowerShell: `$env:PYTHONUTF8 = "1"`).

## Pipeline (built, first version)

Agreed with the user (plan: span-wise first, alignment later):
- **All tag decisions live in `config/policy.yaml`**, mirroring `docs/tag_decisions.md`. Code knows only *roles* (block / container / inline / empty) and *treatments* (translate / keep / transliterate / keep-subtree), never tag names. Each rule may carry `params` (e.g. `num: {treatment: keep, params: {convert: none}}`); unsupported values give a warning. Lookup order: `overrides` (attribute rules, first match) → `tags` → `empty` → `default`.
- **Empty elements are detected per element** (no text, no children) and get the `empty` rule, so `pb`/`milestone`/`gap` aren't listed. A `tags` entry wins over detection.
- **`<note>` is `keep-subtree`**: copied unchanged and kept in place (tag_decisions wins over HANDOVER's language detection).
- **Span-wise translation** (stage 5 / tag placement is deferred): every text piece is translated where it is, so no element moves. `elem.text` gets the element's treatment, `child.tail` the parent's. Text outside blocks is never touched. Nested inline elements: the more protective treatment wins (keep > transliterate > translate). Mixed nesting is decided per element and counted in the report (`inline-as-block`, `inline-with-blocks`, `block-in-block`, ...).
- No placeholders/masking yet: keep spans are never sent to MT.

Flow (`pipeline/document.py: translate_document(path, pair, engine=None, policy=None) -> Result(tree, report)`): parse → `spans.collect_spans` → transliterate (`transliterate.grc_simple`) + one batch to `MTEngine.translate(segments, src, tgt)` → write back keeping whitespace → `xml:lang` src→tgt (not inside kept elements) → add a `<respStmt>` in `titleStmt` → `validate.validate` (well-formed, same elements/attributes in the same order, `@n`/`@xml:id` preserved, kept elements byte-identical, header unchanged). Engines: `identity`, `tag` (wraps output as `[EN:...]`).

## MT engines (`engines/hf.py`, registry in `engines/__init__.py`)

- Names: `opus-grk-en`, `opus-bible-ine` (`Helsinki-NLP/opus-mt-tc-bible-big-ine-deu_eng_nld`), `madlad-3b`, `pivot-grc-el-en` (= `nllb-ag-mg` then `opus-el-en`); any model via `marian:<HF id>` / `madlad:<HF id>`. `engine.name` is the HF model id (goes into the respStmt); a chain's name is `first -> second`.
- `engines/chain.py: ChainEngine(first, second, pivot)` runs src→pivot→tgt and keeps the pivot text in `last_intermediate`. `NllbLoraEngine` (ILSP `ilsp/nllb-200-600M-ag-mg-lora`, CC BY-NC): tokenizer from the adapter repo (148 added polytonic chars), base `facebook/nllb-200-distilled-600M` resized, adapter merged; `ell_Grek` on both sides (`forced_bos_token_id`), so it only accepts tgt `el`. The adapter repo is ~2 GB and the base downloads both .bin and .safetensors (~4.6 GB).
- `HFSeq2SeqEngine` base: lazy import of torch/transformers on first `translate()` (pipeline works without the extra); models cached in `models/hf/` unless `HF_HOME`/`HF_HUB_CACHE` is set; GPU used if available. Each segment is split into sentences (`split_for_mt`: `. ! ? ;` and U+037E; over-long sentences at `, : ·` then words, measured in tokens), pieces deduplicated, translated in length-sorted batches (beam 4), joined with spaces.
- `MarianEngine` finds a `>>eng<<`-style target token from the vocab (ISO 639-1 → 639-3 map) or takes `target_token`; single-target models get no prefix. `MadladEngine` prefixes `<2en>`, bfloat16 on GPU (T5 overflows in fp16). MADLAD has not been run yet (no GPU on the user's laptop; ~12 GB RAM in fp32 on CPU).
- Generation uses each model's defaults (no repetition penalty); Opus models loop on input they don't understand (e.g. Homer).
- `tie_output_embeddings` (called in `HFSeq2SeqEngine._load`): Transformers 5 no longer ties `lm_head` to the embeddings when a checkpoint stores both with different values; `opus-mt-tc-big-el-en` then outputs random words. We tie whenever `config.tie_word_embeddings` is true. If a new model outputs word salad even on easy input, check this first.
- Current ranking (54 passages): `pivot-grc-el-en` chrF 30.4 > `opus-bible-ine` 23.7 ≈ `opus-grk-en` 22.6; most pivot errors come from step 1 (NLLB).
- `scripts/compare_engines.py` (`--reuse RUN_DIR` reuses an earlier run's passages/translations and only runs new engines; writes `run.json` with models/timings): plain-text bake-off on Perseus prose sections + Pindar odes aligned by citation ref (leaf textpart divs; notes/bibl/head/reg removed — `<reg>` holds gazetteer text in some English files), corpus chrF/BLEU overall and per work → `outputs/compare/<timestamp>/`. Results (Opus models + pivot chain): `docs/engine_comparison.md`.

Later (HANDOVER ideas, not agreed): alignment-based tag placement, placeholders, real engines after the bake-off, tei_all validation, name lists for standard English forms.

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

Done: project skeleton, first span-wise pipeline with test engines and validation, Opus-MT/MADLAD/NLLB-LoRA engine wrappers, the `pivot-grc-el-en` chain, and a comparison of the Opus models and the chain. Still open:
- The user raised "which languages to use and how to present them" in the UI. Settle this: which source/target language pairs to offer, and how language and option choices appear in the UI.
- The engine choice (local and hosted), and the open questions at the end of `HANDOVER.md`.

## Commands

Python 3.10+ on Windows (user has 3.14, CPU only). `pip` may not be on PATH: use `python -m pip` / `python -m pytest`. Dependencies (`lxml`, `pyyaml`, `sacrebleu`) are installed by `pip install -e .`; model engines need `pip install -e .[mt]`.

```
pip install -e .[dev]                    # install the package (editable) + pytest
python scripts/data/count_tags.py        # clones Perseus into data/raw/canonical-greekLit/ on first run, writes data/catalog/*.csv and data/stats/tei_tag_frequencies.csv
python scripts/data/build_dataset.py     # downloads Greek/English pairs into data/perseus/, classifies works (poetry/prose/drama)
python scripts/data/count_perseus_tags.py  # tag counts over data/perseus/ (needs build_dataset.py first): data/stats/perseus_tag_frequencies_{greek,all}.csv
python scripts/check_metric_cases.py     # runs the tag-placement, structure and translation metrics on tests/fixtures/metrics/*.json, prints PASS/FAIL per case
python -m tei_translate translate IN.xml --engine tag   # writes outputs/<name>.en.xml, prints rules fired + validation; exit 1 if a check fails
python scripts/compare_engines.py --engines opus-grk-en opus-bible-ine   # MT bake-off on Perseus passages -> outputs/compare/
```

`python -m pytest` runs the suite: `tests/test_metrics.py` (one test per hand-made metric case in `tests/fixtures/metrics/`), `tests/test_policy.py` and `tests/test_pipeline.py` (pipeline, on `tests/fixtures/tei/`), `tests/test_engines.py` (registry, splitting, prefixes; real-model tests only with `TEI_TRANSLATE_RUN_MODELS=1`). `python -m pytest tests/test_pipeline.py::test_names` runs one test. `scripts/check_metric_cases.py` runs the metric cases with longer failure explanations.

## Existing assets worth reusing

- `data/catalog/greek_english_pairs.csv` / `greek_english_texts.csv` — every Greek file in Perseus that has an English translation, with paths; useful for the data loader. Perseus file naming (paths inside the Perseus repo, i.e. under `data/raw/canonical-greekLit/`): `data/TEXTGROUP/WORK/TEXTGROUP.WORK.perseus-{grc,eng}N.xml`; prefer higher `N` (version 1 files are often not CTS-compliant).
- `data/stats/tei_tag_frequencies.csv` — per-tag counts inside `<text>` (Greek vs English), basis for `tag_decisions.md`.
- `src/tei_translate/metrics/scores.py` (import as `tei_translate.metrics.scores`) + `tests/fixtures/metrics/` — verified implementation of tag accuracy and average distance (positions = character offsets in tag-stripped text; requires identical text in reference and hypothesis) plus XML accuracy / XML matching. `src/tei_translate/metrics/translation_scores.py` — corpus-level chrF and BLEU via sacrebleu, tags removed with `fragments.strip_tags` (best effort for broken XML), several references per passage allowed.
