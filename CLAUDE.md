# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A university group project (Essentials of Text and Speech Processing): translate TEI XML documents from Ancient Greek to English while keeping the XML valid and respecting what each tag means. Corpus: Perseus `canonical-greekLit`. The design must stay language-pair agnostic.

**State of the repo:** the project skeleton is set up (installable package, folder layout, `pyproject.toml`), but the translation pipeline does not exist yet. What exists is exploratory work: Perseus data scripts, corpus/tag statistics, and the evaluation metrics (now part of the package, so they are meant to be reused). We are still planning the pipeline itself.

## Key documents (read before planning or coding)

- `docs/HANDOVER.md` — a draft proposal, **not yet reviewed by the team**: treat its "decisions", pipeline, layout, engine choices and milestones as suggestions to discuss, not settled facts. Confirm with the user before relying on any of it.
- `docs/tag_decisions.md` — the team's per-tag decisions with corpus counts (✅ decided, 🟡 still open). Where it disagrees with the `HANDOVER.md` policy table, `tag_decisions.md` reflects team agreement — e.g. it says `<note>` and everything inside it is copied unchanged, whereas HANDOVER proposes language detection. Flag such conflicts rather than silently picking one.
- `docs/feedback_overview.md` — feedback on the proposal and open decisions. `docs/proposed_tasks.md` — who on the team owns what (Ennio: MT model testing; Andjela: texts/tags; Ilaria: evaluation metrics).
- Open questions listed at the end of `HANDOVER.md` (hardware, name convention, `<del>`/`<choice>` defaults, extra features) must be asked, not assumed.

## Repo layout (set up)

Installable package in `src/tei_translate/` (src layout, `pip install -e .[dev]`): `pipeline/`, `engines/`, `ui/` (empty placeholders), `metrics/` (`fragments.py`, `scores.py`, `translation_scores.py`). Entry points live outside the package: `scripts/` (one-off utilities; `scripts/data/` for Perseus data), and later a root `app.py` for Gradio / HF Spaces. Other folders: `config/` (policy and pair configs, later), `data/catalog/` + `data/stats/` (tracked CSVs), `data/raw/` + `data/perseus/` (git-ignored downloads), `models/`, `outputs/`, `logs/` (contents git-ignored, `.gitkeep` only), `docs/`, `tests/` (`tests/fixtures/metrics/` = metric test cases). `pyproject.toml` runtime dependencies: only `sacrebleu` (chrF/BLEU in `metrics/translation_scores.py`); add each new one when code that needs it lands.

Layout decisions agreed with the user (don't relitigate):
- **src layout, package `tei_translate`**, chosen over a flat package. Everyone runs `pip install -e .[dev]` first; anything that imports `tei_translate` fails with `ModuleNotFoundError` otherwise.
- **Minimal dependencies**: the user chose not to pre-declare planned deps (lxml, gradio, transformers, ...). Add them to `pyproject.toml` together with the code that uses them; heavy ML deps should go in an optional extra so the base install stays light.
- **Entry points live outside the package**: `scripts/` for one-off utilities, a root `app.py` for Gradio (needed by HF Spaces, which runs `app.py` from the repo root). When `app.py` is added, the Space also needs a `requirements.txt` containing `.` so it installs the package. A CLI, if built, goes in `src/tei_translate/cli.py` (`python -m tei_translate ...`).
- Reusable code goes in the package; generated or large files have a fixed git-ignored home (`data/raw`, `data/perseus`, `models`, `outputs`, `logs`). Code writing there should still `mkdir(parents=True, exist_ok=True)`.

Notes on the scripts:
- `scripts/data/` scripts are stdlib-only and resolve paths from the repo root (`Path(__file__).resolve().parents[2]`), so they work from any folder without installing. `build_dataset.py` imports its sibling `make_work_types.py` by plain name (`from make_work_types import ...`), so the two must stay in the same folder.
- Since the move, `build_dataset.py` / `make_work_types.py` were only checked with `--help` (a full run downloads every pair from GitHub). `count_tags.py` and `check_metric_cases.py` were run and give the same results as before (44/44 metric checks passed then, CSVs unchanged; with the translation metrics added it is now 59/59).
- On Windows, printing Greek can raise `UnicodeEncodeError: 'charmap'`: set `PYTHONUTF8=1` (PowerShell: `$env:PYTHONUTF8 = "1"`).

## Proposed architecture (from HANDOVER.md, not yet agreed)

Per document: (1) parse with lxml and segment into block units (`<p>`, citation `<div>`s; verse `<l>` deferred until prose works) → (2) classify inline elements via a declarative policy table in `config/policy.yaml` (translate / protect / name-convention), logging which rule fired → (3) mask protected spans with placeholders like `⟦P3⟧` and strip remaining inline tags, recording offsets → (4) translate plain text through a pluggable `MTEngine` (the only language-pair-dependent stage, selected by `config/pairs/<src>-<tgt>.yaml`) → (5) restore protected spans byte-for-byte and project inline tags back via a pluggable `Aligner` (awesome-align default, UGARIT for Greek), with a fallback chain → (6) validate (well-formedness, tei_all RELAX NG, `@n`/`@xml:id` preservation) and count fallbacks.

Core invariant: **the MT model never sees XML structure**; structure is never generated by a model. `MTEngine.translate(segments, src, tgt)` and `Aligner.align(src_tokens, tgt_tokens)` are batch-oriented.

## Frontend / deployment (decided)

The UI is a Gradio app (one Python codebase with the pipeline). The same app runs locally (`python app.py`, opens in the browser) and is deployed for free on Hugging Face Spaces (CPU-only free tier, so it must work with a CPU-friendly model), with code kept on GitHub. Optional: a static GitHub Pages showcase of precomputed example translations.

Why and what follows from it:
- GitHub Pages is static-only and can't run Python or models, so the hosted app lives on HF Spaces. Code stays on GitHub; a GitHub Action can sync it to the Space. Fine-tuned models can be hosted on the HF Hub.
- The local UI is meant to be easier than the terminal for non-technical users, so the pipeline should be callable as a library: Gradio and the CLI are thin layers over the same functions.
- Local runs can use a GPU and bigger models (e.g. MADLAD 3B). The Space can't, so the engine must be selectable by config. The Space sleeps when idle and suits passages, not whole works.
- `demo.launch(share=True)` gives a temporary public link to a local run, useful for team demos.
- Local users still need to install Python, the dependencies and model downloads, so aim for a single install command and a clear README.

## Planning status

Done: project skeleton (layout, `pyproject.toml`, metrics moved into the package). No pipeline code exists yet. Still open:
- The user raised "which languages to use and how to present them" in the UI. Settle this: which source/target language pairs to offer, and how language and option choices appear in the UI.
- The engine choice (local and hosted), and the open questions at the end of `HANDOVER.md`.
- The `<note>` conflict between `tag_decisions.md` and `HANDOVER.md`.

## Commands

Python 3.10+ on Windows. Only dependency so far: `sacrebleu` (installed by `pip install -e .`).

```
pip install -e .[dev]                    # install the package (editable) + pytest
python scripts/data/count_tags.py        # clones Perseus into data/raw/canonical-greekLit/ on first run, writes data/catalog/*.csv and data/stats/tei_tag_frequencies.csv
python scripts/data/build_dataset.py     # downloads Greek/English pairs into data/perseus/, classifies works (poetry/prose/drama)
python scripts/data/count_perseus_tags.py  # tag counts over data/perseus/ (needs build_dataset.py first): data/stats/perseus_tag_frequencies_{greek,all}.csv
python scripts/check_metric_cases.py     # runs the tag-placement, structure and translation metrics on tests/fixtures/metrics/*.json, prints PASS/FAIL per case
```

`pytest` runs the suite (so far `tests/test_metrics.py`: one test per hand-made metric case in `tests/fixtures/metrics/`, 61 tests), `pytest tests/path::test_name` runs one test. `scripts/check_metric_cases.py` runs the same cases with longer failure explanations. A CLI (`list-units`, later `translate` / `evaluate` / `bakeoff`) is proposed in HANDOVER but not built.

## Existing assets worth reusing

- `data/catalog/greek_english_pairs.csv` / `greek_english_texts.csv` — every Greek file in Perseus that has an English translation, with paths; useful for the data loader. Perseus file naming (paths inside the Perseus repo, i.e. under `data/raw/canonical-greekLit/`): `data/TEXTGROUP/WORK/TEXTGROUP.WORK.perseus-{grc,eng}N.xml`; prefer higher `N` (version 1 files are often not CTS-compliant).
- `data/stats/tei_tag_frequencies.csv` — per-tag counts inside `<text>` (Greek vs English), basis for `tag_decisions.md`.
- `src/tei_translate/metrics/scores.py` (import as `tei_translate.metrics.scores`) + `tests/fixtures/metrics/` — verified implementation of tag accuracy and average distance (positions = character offsets in tag-stripped text; requires identical text in reference and hypothesis) plus XML accuracy / XML matching. `src/tei_translate/metrics/translation_scores.py` — corpus-level chrF and BLEU via sacrebleu, tags removed with `fragments.strip_tags` (best effort for broken XML), several references per passage allowed.
