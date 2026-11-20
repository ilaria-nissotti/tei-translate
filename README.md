# tei-translate
Translate TEI XML documents while preserving tag structure and meaning.

## Requirements
- Python 3.10 or newer
- `git` (used to download the Perseus texts)

## Installation
From the repository root (the folder this README is in), ideally in a virtual environment:

```
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -e .[dev]
```

This installs the `tei_translate` package in editable mode (your code changes apply straight away) plus `pytest`. It also installs the dependencies listed in `pyproject.toml` (`lxml` and `pyyaml` for the pipeline, `sacrebleu` for chrF and BLEU); new ones are added there when code needs them. This is enough for the pipeline with the test engines, all metrics except COMET, and the tests.

To translate with a real MT model, also install the `mt` extra (PyTorch, Transformers, SentencePiece; about 1 GB on disk):

```
pip install -e .[dev,mt]
```

To compute **COMET** scores, install the `comet` extra. The first time COMET runs it downloads its model (`Unbabel/wmt22-comet-da`, about 2.3 GB), so allow about 5 GB of disk space in total:

```
pip install -e .[dev,comet]
```

Extras can be combined: `pip install -e .[dev,mt,comet]`. Only the person computing the final scores needs COMET; nothing else depends on it.

**Running models on an NVIDIA graphics card (optional).** MT models and COMET run on any laptop, on the processor (CPU), just more slowly. With an NVIDIA graphics card they run much faster, but on Windows `pip` installs the CPU-only version of PyTorch by default. To get the GPU version, run this **before** installing the extras:

```
pip install torch --index-url https://download.pytorch.org/whl/cu126
```

Check it worked with `python -c "import torch; print(torch.cuda.is_available())"`: `True` means the GPU is used. Macs and laptops without an NVIDIA card skip this step and use the CPU automatically.

**If `import torch` fails on Windows** with `OSError: [WinError 1114] ... c10.dll`: this happens when the virtual environment was created from **Anaconda's** Python. Anaconda ships an old copy of a Windows C++ library (`msvcp140.dll`), which is loaded instead of the recent one Windows has, and PyTorch cannot start with it. Create the virtual environment from the official Python instead ([python.org](https://www.python.org/downloads/), or `winget install Python.Python.3.11`), e.g.:

```
& "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe" -m venv .venv
```

## Repository layout
```
src/tei_translate/     the Python package (import it as tei_translate)
  pipeline/            pipeline stages (empty for now)
  engines/             MT engines: test engines + Hugging Face models (Opus-MT, MADLAD)
  metrics/             evaluation metrics (fragments.py, scores.py, translation_scores.py, comet_score.py, placement_eval.py)
  ui/                  Gradio app (empty for now)
scripts/
  data/                download and describe the Perseus data (count_tags.py, build_dataset.py, make_work_types.py)
config/                configuration files (tag policy, language pairs), later
data/
  catalog/             which Perseus works have Greek + English (output of count_tags.py)
  stats/               TEI tag statistics (output of count_tags.py)
  raw/                 local clone of Perseus (git-ignored)
  perseus/             downloaded parallel dataset (output of build_dataset.py, git-ignored)
models/                local and fine-tuned MT models (contents git-ignored)
outputs/               translated files and evaluation results (contents git-ignored)
logs/                  run logs (contents git-ignored)
docs/                  proposal, handover, tag decisions, feedback, task split
tests/                 tests (run with pytest); tests/fixtures/metrics/ holds the metric test cases
```

Documents in `docs/`:
- `Essentials_Proposal.pdf`: project proposal
- `HANDOVER.md`: draft pipeline proposal (not yet reviewed by the team)
- `feedback_overview.md`: feedback on the proposal and the open decisions
- `proposed_tasks.md`: who does what
- `tag_decisions.md`: which TEI tags the tool handles, how, and why

## Running the scripts

### `count_tags.py`
```
python scripts/data/count_tags.py
```

The script finds its files relative to the repository root, so it works from any folder.

On the first run it clones the Perseus Greek texts ([canonical-greekLit](https://github.com/PerseusDL/canonical-greekLit)) into `data/raw/canonical-greekLit/`. This folder is git-ignored, so it is never committed. Later runs reuse it.

It writes three CSV files, the first two to `data/catalog/` and the third to `data/stats/`:
- `greek_english_texts.csv`: one row per work that has both a Greek edition and an English translation, with all of its files and a GitHub link
- `greek_english_pairs.csv`: one row per Greek file/English translation pair (a work with 4 English translations gets 4 rows)
- `tei_tag_frequencies.csv`: statistics for each TEI tag, counted only inside `<text>` (the `<teiHeader>` metadata is skipped). Rows are sorted by `greek_with_text`, highest first. Columns:
  - `greek_count`: how often the tag appears in the Greek files
  - `greek_with_text`: how often it has text directly inside it (not only inside its child tags). Empty markers such as `<pb/>` and containers such as `<div>` get 0 or close to it
  - `greek_script_share`: share of that text written in Greek letters (0–1). A low value means the tag mostly holds Latin or English, e.g. editors' notes
  - `greek_inline_share`: share of occurrences found inside a `<p>` or `<l>`, i.e. in the middle of a sentence (0–1)
  - `english_count`, `english_with_text`: the same counts for the English translations

`data/stats/tei_tag_frequencies_prev.csv` is the previous version of `tei_tag_frequencies.csv`, kept for comparison. It counted whole files (including the `<teiHeader>`) and had a `total` column. It is not updated by the script.

At the end the script prints the 15 most frequent inline tags (tags with text and a `greek_inline_share` of at least 0.5). These are the candidates for the tag list.

### `build_dataset.py` and `make_work_types.py`
```
python scripts/data/build_dataset.py
```

Downloads every Greek/English file pair listed in `data/catalog/greek_english_pairs.csv` into `data/perseus/` (git-ignored), writes `data/perseus/pairs.csv`, and classifies each work as poetry, prose or drama from its Greek markup (`work_types.csv`, `work_type_details.csv`). Re-running skips files already downloaded. `python scripts/data/make_work_types.py` redoes only the classification. Both take `--help`.

### Translating a file with an MT engine
Needs the `mt` extra (see Installation). The first use of a model downloads it into `models/hf/` (git-ignored).

```
python -m tei_translate translate IN.xml --engine opus-grk-en
```

| `--engine` | Model | Notes |
|---|---|---|
| `identity`, `tag` | none | test engines: return the input / wrap it as `[EN:...]` |
| `opus-grk-en` | `Helsinki-NLP/opus-mt-grk-en` | small (~300 MB), fast on CPU |
| `opus-bible-ine` | `Helsinki-NLP/opus-mt-tc-bible-big-ine-deu_eng_nld` | larger (~0.9 GB), still fine on CPU |
| `madlad-3b` | `google/madlad400-3b-mt` | 3B parameters, 11.8 GB download; runs in bfloat16 (~6 GB RAM), about 5 Greek words/s on a laptop CPU |
| `pivot-grc-el-en` | `ilsp/nllb-200-600M-ag-mg-lora` → `Helsinki-NLP/opus-mt-tc-big-el-en` | two steps: Ancient → Modern Greek (NLLB-600M + LoRA), then Modern Greek → English. ~7 GB download; the ILSP adapter is CC BY-NC 4.0 (non-commercial) |
| `nllb-ag-mg`, `opus-el-en` | the two halves of `pivot-grc-el-en` | `nllb-ag-mg` only translates into Modern Greek (`el`) |
| `marian:<model id>` | any Opus-MT model on Hugging Face | e.g. `marian:Helsinki-NLP/opus-mt-tc-big-el-en` |
| `madlad:<model id>` | another MADLAD-400 size | e.g. `madlad:google/madlad400-7b-mt` |

The default engine is set in `config/pairs/grc-en.yaml`.

### `compare_engines.py`
Compares MT engines on Perseus passages (plain text, no XML) against the Perseus English translations, with chrF and BLEU. Needs `data/perseus/` (`build_dataset.py`) and the `mt` extra:

```
python scripts/compare_engines.py                                  # opus-grk-en vs opus-bible-ine
python scripts/compare_engines.py --engines opus-grk-en madlad-3b --per-work 4
python scripts/compare_engines.py --reuse outputs/compare/<earlier run> --engines opus-grk-en opus-bible-ine pivot-grc-el-en
```

It writes `outputs/compare/<timestamp>/report.md` (scores overall and per work, with examples), `translations.jsonl` (every passage with each engine's output, plus the Modern Greek in between for `pivot-grc-el-en`) and `run.json` (settings, models, timings). `--reuse` takes the passages and translations of an earlier run and only runs the engines it doesn't have yet, so adding an engine to a comparison doesn't re-run the others. For a slow engine, add `--subset N` (first N passages per work) and/or `--max-words W` (only passages up to W Greek words): every engine is then scored on that smaller set.

### `eval_placement.py`
Scores how well the hybrid pipeline places the tags, against the gold set in `data/gold/grc-en/` (English TEI files with the tags placed correctly, listed in `translations.csv`; see `docs/gold_set_handover.md`):

```
python scripts/eval_placement.py                                   # the baselines none, monotone, sentence (no models)
python scripts/eval_placement.py --aligners none monotone sentence xlmr ugarit
python scripts/eval_placement.py --gold-dir tests/fixtures/placement_eval/gold --perseus tests/fixtures/placement_eval/perseus   # the test data
```

Methods to compare (`--aligners`): the word aligners `ugarit` (the pipeline's default, trained for Ancient Greek) and `xlmr` (the same kind of model without Ancient Greek training); and three baselines without a model: `none` (no alignment: a tag that needs it takes its fallback, usually the block is not placed), `monotone` (assumes the English words follow the Greek order) and `sentence` (no alignment: a tag that needs it covers its whole English sentence). `dragoman` is left out for now: its tokenizer does not load with the installed Transformers version, so almost every block would be an aligner error.

The Greek source of each gold file is read from `data/perseus/` or, if that folder is missing, from the local Perseus clone `data/raw/canonical-greekLit/`. The model aligners need `pip install -e .[mt]`.

How it works: each Greek text block (paragraph) is paired with the gold block in the same position (both files have the same structure). The pipeline's placement step then places the Greek block's tags into the **gold English text** (not into its own translation), so the only thing that can differ from the gold is where the tags are. The pipeline places tags sentence by sentence, so the gold English sentences are matched to the Greek ones: one to one if there are as many; if the translator split a Greek sentence, consecutive English sentences are grouped per Greek sentence by length; if there are fewer English sentences, the whole block is one unit. The result is compared with the gold tags:
- **strict accuracy** (the headline number): gold tags at exactly the right place, over all gold tags of the placeable blocks; tags in blocks the method could not place (or where the aligner failed) count as wrong, so every method is measured on the same tags;
- **tag accuracy**: the same, but only over the blocks the method could place (a method that gives up on hard blocks looks better, so this number does not compare methods);
- **average distance**: how many characters off the tags are;
- **fallback rate**: blocks the pipeline could not place (it would translate them span-wise).

Scoring rules: positions are counted without spaces and without punctuation, so a tag on either side of a space, quotation mark, comma or full stop is at the same place (translators put quotation marks inside or outside `<q>` inconsistently; `--keep-punctuation` counts punctuation, for a stricter check); an opening and a closing tag count as two tags; notes and references count as single points (their content is copied unchanged and not compared); fixed elements (`label`, `speaker`, `term`, `foreign`, which the pipeline keeps or transliterates) are scored before the pipeline replaces their English with their own content (`--policy-as-is` turns this off). Names and numbers are translated by the model, so they are ordinary tags.

It writes `outputs/eval_placement/<timestamp>/report.md` (the scores per aligner, per tag type, per sentence mode and per gold file, and why blocks could not be placed), `results.jsonl` (every block with its status, scores and rebuilt text), `summary.json` and `run.json`.

### `eval_translation.py`
Translation quality per MT engine: chrF, BLEU and COMET, on the passages and translations of a `compare_engines.py` run (so no engine has to run again):

```
python scripts/eval_translation.py --run outputs/compare/<run>             # chrF, BLEU, COMET
python scripts/eval_translation.py --run outputs/compare/<run> --no-comet  # only chrF and BLEU
```

References are the Perseus English translations. Text only: tags play no part. COMET (`Unbabel/wmt22-comet-da`) compares each translation with its best reference and also reads the Greek; it was not trained on Ancient Greek, so treat it as a second opinion next to chrF. It needs `pip install -e .[comet]` and downloads the model (about 2.3 GB) the first time. A quick version: `compare_engines.py --engines madlad-3b opus-bible-ine --per-work 3` (21 passages) and then this script.

It writes `outputs/eval_translation/<timestamp>/report.md` (scores per engine, overall and per work), `scores.jsonl` (COMET per passage), `summary.json` and `run.json`.

### `eval_end_to_end.py`
Translation and tags together: runs the real pipeline (MT engine + aligner) on the Greek source of the gold files and compares its English TEI with the gold English TEI:

```
python scripts/eval_end_to_end.py --files tlg0062.tlg006 tlg0062.tlg054 --conditions plain hybrid spanwise --comet
python scripts/eval_end_to_end.py --max-files 3 --max-blocks 40           # first 40 text blocks of the first 3 gold files
python scripts/eval_end_to_end.py --engine identity --aligner monotone    # quick check without models
```

Conditions: `hybrid` (the pipeline's default), `spanwise` (every text piece translated where it is) and `plain` (the text without tags, as one segment per block: the upper bound for translation quality). Every condition is scored on the same blocks: those the hybrid pipeline handles, where the gold block is translated. Scores: share of files passing the pipeline's validator, structure match (blocks with exactly the gold's tags), chrF / BLEU / COMET on the text, and Node-chrF (the right words inside the right tags). The defaults are `madlad-3b` and `ugarit`, as in the pipeline. MADLAD does about 5–8 Greek words per second on a laptop CPU, so choose a few files with `--files` (dot-separated ids, e.g. `tlg0062.tlg006`), `--max-files` or `--max-blocks`.

It writes `outputs/eval_end_to_end/<timestamp>/report.md`, `units.jsonl` (every scored block: Greek, gold and each condition's output), `summary.json`, `run.json`, and the English TEI files in `hybrid/` and `spanwise/`.

### Running the tests
From the repository root, with the package installed (see Installation):

```
pytest
```

This runs every test in `tests/` and prints one dot per passing test, or the details of a failing one. `pytest -v` prints one line per test, and `pytest -k structure` runs only the tests whose name contains "structure". Run `pytest` after changing anything in the metrics.

The tests that run real MT models (`tests/test_engines.py`) are skipped by default because they download models. To run them: `$env:TEI_TRANSLATE_RUN_MODELS = "1"; pytest tests/test_engines.py` (PowerShell).

The metric tests are in `tests/test_metrics.py`. Each hand-made case in `tests/fixtures/metrics/` is one test (the cases are described in that folder's README):
- `cases.json`: the tag-placement metrics from Zenkel et al. (2021), tag accuracy and average distance, plus the lists of misplaced, missing and extra tags and the score per tag type.
- `structure_cases.json`: the structure metrics from Hashimoto et al. (2019), XML accuracy (is the output valid XML?) and XML matching (does it have exactly the same tags as the input?).
- `translation_cases.json`: removing tags (also from broken XML), and chrF and BLEU: several references are handled correctly, and the scores equal sacrebleu's on the plain text.
- `node_chrf_cases.json`: Node-chrF from Song et al. (2025): which elements are paired, with which texts, and the resulting scores.

The placement evaluation is tested in `tests/test_placement_eval.py`, on a hand-made Greek file and its gold translation (`tests/fixtures/placement_eval/`); the end-to-end evaluation in `tests/test_end_to_end.py`, on the same files with a word-by-word test engine; the translation evaluation in `tests/test_translation_eval.py`, on a tiny made-up `compare_engines.py` run. COMET is tested in `tests/test_comet.py`, mostly with a simple stand-in for the model; the tests with the real model run only with `TEI_TRANSLATE_RUN_MODELS=1`.

A failing test shows the case's description and which values differ from the expected ones.

## Using the metrics in your own code
The metrics are in `src/tei_translate/metrics/`, one function per metric: tag placement and structure in `scores.py`, translation quality (chrF, BLEU, Node-chrF) in `translation_scores.py`. Once the package is installed (see Installation), import them from any script, in any folder:

```python
from tei_translate.metrics.scores import tag_accuracy, average_distance, score
from tei_translate.metrics.scores import is_valid_xml, xml_accuracy, same_structure, xml_matching
from tei_translate.metrics.translation_scores import chrf, bleu, node_chrf, node_chrf_corpus
from tei_translate.metrics.comet_score import comet, comet_scores          # needs pip install -e .[comet]
```

If you get `ModuleNotFoundError: No module named 'tei_translate'`, the package is not installed in the Python you are using: activate the virtual environment, or run `pip install -e .` again.

All inputs are XML fragments as strings, e.g. `'<said who="#Σωκράτης"><label>ΣΩ.</label> ...</said>'`. Arguments always come in the order reference (or Greek input) first, output second.

| Function | Gives | Input |
|---|---|---|
| `tag_accuracy(reference, hypothesis)` | share of tags in exactly the right place (0–1) | one passage; same text in both |
| `average_distance(reference, hypothesis)` | average number of characters the tags are off | one passage; same text in both |
| `score(reference, hypothesis)` | both of the above, plus lists of misplaced, missing and extra tags and a score per tag type | one passage; same text in both |
| `is_valid_xml(hypothesis)` | `True` if the output is valid XML | one output |
| `xml_accuracy(hypotheses)` | share of outputs that are valid XML (0–1) | list of outputs |
| `same_structure(source, hypothesis)` | `True` if the output has exactly the same tags as the Greek input | one passage |
| `xml_matching(sources, hypotheses)` | share of outputs with the same tags as their input (0–1) | two lists in the same order |
| `chrf(references, hypotheses)` | chrF of the whole test set (0–100), tags removed | two lists in the same order; each reference can be one string or a list of several translations |
| `bleu(references, hypotheses)` | BLEU of the whole test set (0–100), tags removed | as for `chrf` |
| `node_chrf(reference, hypothesis)` | are the right words inside each tag? chrF per element, averaged (0–100) | one passage; the reference must have the same tags as the output should have |
| `node_chrf_corpus(references, hypotheses)` | average `node_chrf` over passages (0–100) | two lists in the same order, one reference per passage |
| `comet(sources, references, hypotheses)` (in `tei_translate.metrics.comet_score`) | COMET of the whole test set (usually 0–1), tags removed: the average of the passages' scores | three lists in the same order: Greek inputs, references (one string or a list per passage), outputs |
| `comet_scores(sources, references, hypotheses)` | COMET of each passage | as for `comet` |
| `strip_tags(fragment)` (in `tei_translate.metrics.fragments`) | the text without tags, whitespace normalised | one fragment |

`chrf` and `bleu` score the **whole test set at once**: averaging per-passage scores would give a different, wrong number. With several references, chrF uses the best-matching one for each passage; BLEU lets words match in any of them; COMET scores each passage against every reference and keeps the best score (like chrF). Outputs that are not valid XML are still scored: everything of the form `<...>` is removed first, and the broken XML shows up in `xml_accuracy` instead.

A score that cannot be computed is `None`: e.g. `tag_accuracy` when the output is not valid XML, or its text differs from the reference. What each metric means, with examples, is explained in `tests/fixtures/metrics/README.md`.

Example:

```python
from tei_translate.metrics.scores import tag_accuracy, average_distance, same_structure

ref = 'Then <name>Socrates</name> said.'
hyp = 'Then Socrates <name>said</name>.'
tag_accuracy(ref, hyp)        # 0.0
average_distance(ref, hyp)    # 7.0  (<name> is 9 characters off, </name> 5)

greek = '<said who="#Σωκράτης"><label>ΣΩ.</label> πάνυ γε.</said>'
output = '<said who="#Σωκράτης">Soc. Certainly.</said>'
same_structure(greek, output) # False: the <label> tag was lost
```

`is_valid_xml` and `same_structure` can also be used **inside the pipeline**, to check each translated passage straight away (e.g. log or retry when the output lost a tag).

To try the functions interactively, type `python` and import them as above. If printing Greek text gives `UnicodeEncodeError: 'charmap' codec ...`, run `$env:PYTHONUTF8 = "1"` (PowerShell) once in that terminal first.
