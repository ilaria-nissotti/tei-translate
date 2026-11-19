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

This installs the `tei_translate` package in editable mode (your code changes apply straight away) plus `pytest`. It also installs the dependencies listed in `pyproject.toml` (for now only `sacrebleu`, used for chrF and BLEU); new ones are added there when code needs them.

To translate with a real MT model, also install the `mt` extra (PyTorch, Transformers, SentencePiece; about 1 GB on disk):

```
pip install -e .[dev,mt]
```

## Repository layout
```
src/tei_translate/     the Python package (import it as tei_translate)
  pipeline/            pipeline stages (empty for now)
  engines/             MT engines: test engines + Hugging Face models (Opus-MT, MADLAD)
  metrics/             evaluation metrics (fragments.py, scores.py, translation_scores.py)
  ui/                  Gradio app (empty for now)
scripts/
  data/                download and describe the Perseus data (count_tags.py, build_dataset.py, make_work_types.py)
  check_metric_cases.py   checks the metrics on the hand-made test cases
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
| `madlad-3b` | `google/madlad400-3b-mt` | 3B parameters (~12 GB): a GPU is strongly recommended |
| `marian:<model id>` | any Opus-MT model on Hugging Face | e.g. `marian:Helsinki-NLP/opus-mt-tc-big-el-en` |
| `madlad:<model id>` | another MADLAD-400 size | e.g. `madlad:google/madlad400-7b-mt` |

The default engine is set in `config/pairs/grc-en.yaml`.

### `compare_engines.py`
Compares MT engines on Perseus passages (plain text, no XML) against the Perseus English translations, with chrF and BLEU. Needs `data/perseus/` (`build_dataset.py`) and the `mt` extra:

```
python scripts/compare_engines.py                                  # opus-grk-en vs opus-bible-ine
python scripts/compare_engines.py --engines opus-grk-en madlad-3b --per-work 4
```

It writes `outputs/compare/<timestamp>/report.md` (scores overall and per work, with examples) and `translations.jsonl` (every passage with each engine's output).

### Running the tests
From the repository root, with the package installed (see Installation):

```
pytest
```

This runs every test in `tests/` and prints one dot per passing test, or the details of a failing one. `pytest -v` prints one line per test, and `pytest -k structure` runs only the tests whose name contains "structure". For now the tests are in `tests/test_metrics.py`: each hand-made metric case in `tests/fixtures/metrics/` is one test. Run `pytest` after changing anything in the metrics.

The tests that run real MT models (`tests/test_engines.py`) are skipped by default because they download models. To run them: `$env:TEI_TRANSLATE_RUN_MODELS = "1"; pytest tests/test_engines.py` (PowerShell).

### `check_metric_cases.py`
Runs the same metric cases as `pytest`, but explains each failure in words, which helps when a metric case fails. Needs the package installed (see Installation):

```
python scripts/check_metric_cases.py
```

It checks the tag-placement metrics in `src/tei_translate/metrics/scores.py`, from Zenkel et al. (2021): tag accuracy (share of tags in exactly the right place) and average distance (how many characters off they are), plus lists of misplaced, missing and extra tags and a score per tag type. It runs them on every case in `tests/fixtures/metrics/cases.json` and prints `PASS` or `FAIL` for each one. For a failed case it shows which tags were judged differently from the expected result, with the tag marked in the sentence (e.g. `"Theo.[</label>] We bring..."`), and the expected and actual scores. If the output is not valid XML or its text differs from the reference, it shows where.

It also checks the structure metrics from Hashimoto et al. (2019) on every case in `tests/fixtures/metrics/structure_cases.json`: XML accuracy (is the output valid XML?) and XML matching (does it have exactly the same tags as the input?). For a failed case it lists which tags are in the input but not the output, or the other way round.

Finally it checks the translation metrics on `tests/fixtures/metrics/translation_cases.json`: that tags are removed correctly (also from broken XML), that several references are handled correctly, and that `chrf`/`bleu` give the same result as sacrebleu on the plain text.

## Using the metrics in your own code
The metrics are in `src/tei_translate/metrics/`, one function per metric: tag placement and structure in `scores.py`, translation quality (chrF, BLEU) in `translation_scores.py`. Once the package is installed (see Installation), import them from any script, in any folder:

```python
from tei_translate.metrics.scores import tag_accuracy, average_distance, score
from tei_translate.metrics.scores import is_valid_xml, xml_accuracy, same_structure, xml_matching
from tei_translate.metrics.translation_scores import chrf, bleu
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
| `strip_tags(fragment)` (in `tei_translate.metrics.fragments`) | the text without tags, whitespace normalised | one fragment |

`chrf` and `bleu` score the **whole test set at once**: averaging per-passage scores would give a different, wrong number. With several references, chrF uses the best-matching one for each passage; BLEU lets words match in any of them. Outputs that are not valid XML are still scored: everything of the form `<...>` is removed first, and the broken XML shows up in `xml_accuracy` instead.

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
