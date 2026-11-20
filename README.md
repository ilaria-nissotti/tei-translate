# tei-translate

Translates TEI XML files from Ancient Greek to English and keeps the tags in the right places.
How it works: [docs/pipeline.md](docs/pipeline.md).

## Install

You need Python 3.10+ and `git`. From the repo folder:

```
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e .[dev]
```

That's enough for the pipeline with the test engines, the metrics (except COMET) and the tests.
Extras:

- `pip install -e .[dev,mt]` for real translation models (PyTorch, Transformers; ~1 GB).
- `pip install -e .[dev,comet]` for COMET (downloads a 2.3 GB model on first use).

**GPU (optional).** On Windows, pip installs the CPU-only PyTorch. For an NVIDIA card, run
`pip install torch --index-url https://download.pytorch.org/whl/cu126` before the extras.

**`import torch` fails with `WinError 1114 ... c10.dll`?** Your venv was made from Anaconda's
Python. Make it from the python.org Python instead.

**`UnicodeEncodeError: 'charmap'` when printing Greek?** Run `$env:PYTHONUTF8 = "1"` (PowerShell).

## Translate a file

```
python -m tei_translate translate IN.xml                    # default engine: madlad-3b
python -m tei_translate translate IN.xml --engine tag       # no model, for testing
```

The result goes to `outputs/<name>.en.xml` and a report is printed. Models download into
`models/hf/` the first time.

| `--engine` | Model | Notes |
|---|---|---|
| `madlad-3b` | `google/madlad400-3b-mt` | default; 11.8 GB, ~5 words/s on a laptop CPU |
| `pivot-grc-el-en` | `ilsp/nllb-200-600M-ag-mg-lora` → `opus-mt-tc-big-el-en` | via Modern Greek; ~7 GB; non-commercial licence |
| `opus-grk-en`, `opus-bible-ine` | Helsinki-NLP Opus-MT | small and fast, but much worse |
| `identity`, `tag` | none | test engines: copy the input / wrap it as `[EN:...]` |
| `marian:<id>`, `madlad:<id>` | any Opus-MT / MADLAD model | e.g. `madlad:google/madlad400-7b-mt` |

Other options:

- `-o/--output OUT.xml`: where to write the result (default `outputs/<name>.<tgt>.xml`).
- `--aligner ugarit|xlmr|dragoman|monotone|none` and `--placement hybrid|spanwise`: how tags are
  put back into the translation.
- `--pair PAIR.yaml`: language-pair config (default `config/pairs/grc-en.yaml`).
- `--policy POLICY.yaml`: a different tag-rules file.

The defaults for engine, aligner, placement, policy and schema come from the pair config, so the
options above only override it.

## Configuration

- **Tag rules**: `config/policy.yaml` says what happens to each TEI tag (translate, keep,
  transliterate, copy unchanged) and how it is placed back. The code only knows these rules, never
  tag names, so changing how a tag is handled means editing this file. The reasons for each rule
  are in [tag_decisions.md](docs/tag_decisions.md).
- **Language pairs**: `config/pairs/grc-en.yaml` holds everything pair-specific (`src`, `tgt`,
  engine, aligner, placement, policy, schema). For another pair, copy it, change the values and
  pass it with `--pair`. The engine must support the pair, and transliteration is only
  implemented for Greek.

To read the output comfortably, open it in the [Mano Project viewer](https://mano-project.github.io/viewer.html).

## Scripts

Data (no install needed):

- `python scripts/data/count_tags.py`: clones Perseus into `data/raw/` and writes the list of
  Greek works with English translations (`data/catalog/`) and tag counts (`data/stats/`).
- `python scripts/data/build_dataset.py`: downloads those Greek/English pairs into `data/perseus/`
  and labels each work as prose, poetry or drama.
- `python scripts/data/count_perseus_tags.py`: tag counts over `data/perseus/` (needs
  `build_dataset.py` first), written to `data/stats/perseus_tag_frequencies_{greek,all}.csv`.

Gold set:

- `python scripts/gold/check_gold.py GREEK.xml GOLD.xml`: checks a gold English translation
  against its Greek source: runs the pipeline's validation checks, lists missing or extra tags per
  block, and flags Greek left untranslated outside kept elements. Run it before adding a file to
  `data/gold/grc-en/`.

Experiments (need `data/perseus/` and the `mt` extra; results go to `outputs/`):

- `compare_engines.py`: plain-text translation quality per engine (chrF, BLEU).
  `--reuse <run>` adds engines to an earlier run without re-running the others.
- `compare_spanwise.py`: whole-passage vs span-wise vs hybrid translation on the same passages.
- `bench_engine_threads.py`: speed and memory with few CPU threads (like the free HF Space).
- `check_schema_corpus.py`: runs the pipeline on every Greek file and checks the TEI schema.

Evaluation:

- `eval_translation.py --run outputs/compare/<run>`: chrF, BLEU and COMET per engine.
- `eval_placement.py --aligners none monotone sentence xlmr ugarit`: how well tags are placed,
  measured on the gold set (`data/gold/grc-en/`). The pipeline places the Greek tags into the
  gold English text, so only the tag positions can differ. Main score: strict accuracy (share of
  gold tags in exactly the right place; spaces and punctuation ignored).
- `eval_end_to_end.py --max-files 3 --max-blocks 40`: the whole pipeline on the gold set's Greek,
  compared with the gold English: validity, structure, chrF/COMET, Node-chrF.

Every script has `--help`.

## Tests

```
pytest
```

Tests that download real models are skipped unless you set `$env:TEI_TRANSLATE_RUN_MODELS = "1"`.
The metric test cases are in `tests/fixtures/metrics/` (explained in its README).

## Using the metrics

```python
from tei_translate.metrics.scores import (tag_accuracy, average_distance, score,
    is_valid_xml, xml_accuracy, same_structure, xml_matching)
from tei_translate.metrics.translation_scores import chrf, bleu, node_chrf, node_chrf_corpus
from tei_translate.metrics.comet_score import comet          # needs the comet extra
```

Inputs are XML fragments as strings. The reference (or Greek input) always comes first.

| Function | Gives |
|---|---|
| `tag_accuracy(ref, hyp)` | share of tags in the right place (0–1); text must be the same in both |
| `average_distance(ref, hyp)` | how many characters the tags are off |
| `score(ref, hyp)` | both, plus misplaced/missing/extra tags and a score per tag type |
| `is_valid_xml(hyp)`, `xml_accuracy(hyps)` | is the output valid XML / share that is |
| `same_structure(src, hyp)`, `xml_matching(srcs, hyps)` | same tags as the input / share that has |
| `chrf(refs, hyps)`, `bleu(refs, hyps)` | corpus score (0–100), tags removed; a reference can be a list |
| `node_chrf(ref, hyp)` | are the right words inside each tag? |
| `comet(srcs, refs, hyps)` | COMET, tags removed |

`chrf` and `bleu` score the whole test set at once (don't average per-passage scores). A score
that can't be computed is `None`.

```python
tag_accuracy('Then <name>Socrates</name> said.', 'Then Socrates <name>said</name>.')  # 0.0
```

## Layout

```
src/tei_translate/   the package: pipeline/, engines/, align/, metrics/, cli.py, ui/ (empty)
scripts/             experiments and evaluation; data/ for Perseus, gold/ for the gold set
config/              tag rules (policy.yaml), language pairs (pairs/), TEI schema (schemas/)
data/                catalog/ and stats/ (CSVs), gold/ (gold set); raw/ and perseus/ are downloads
models/ outputs/ logs/   local files, not in git
docs/                see below
tests/
```

Docs:

- [pipeline.md](docs/pipeline.md): how a file gets translated, and what's left to do. Start here.
- [tag_decisions.md](docs/tag_decisions.md): what we do with each TEI tag, and why.
- [engine_comparison.md](docs/engine_comparison.md): which translation model, and why MADLAD.
- [spanwise_cost.md](docs/spanwise_cost.md): what it costs to cut sentences at tags.
- [gold_chunk_workflow.md](docs/gold_chunk_workflow.md): how long texts are split up for the gold translations.
- `Essentials_Proposal.pdf`: the project proposal.

## Not built yet

A Gradio app (`app.py`) for translating in the browser, run locally and on a free Hugging Face
Space. `src/tei_translate/ui/` is a placeholder for it.

## Credits and licences

University group project for *Essentials of Text and Speech Processing*, by Ennio, Andjela and
Ilaria.

- Texts: Perseus Digital Library,
  [canonical-greekLit](https://github.com/PerseusDL/canonical-greekLit), CC BY-SA 4.0.
- Schema: TEI P5 `tei_all` 4.12.0 (see `config/schemas/README.md`).
- Models are downloaded at run time and keep their own licences. Check them before reusing the
  output: `ilsp/nllb-200-600M-ag-mg-lora` (used by `pivot-grc-el-en`) is CC BY-NC (non-commercial),
  and the UGARIT and Dragoman aligners are CC BY 4.0. MADLAD-400 and Opus-MT list their licences
  on their Hugging Face model pages.
