# tei-translate
Translate TEI XML documents while preserving tag structure and meaning.

## Requirements
- Python 3 (the scripts only use the standard library, so no `pip install` is needed yet)
- `git` (used to download the Perseus texts)

## Repository layout
- `Essentials_Proposal.pdf`: project proposal
- `feedback_overview.md`: feedback on the proposal and the open decisions
- `proposed_tasks.md`: who does what
- `tag_decisions.md`: which TEI tags the tool handles, how, and why
- `texts/counting_script.py`: finds the Perseus works that have both Greek and English versions and counts their TEI tags
- `texts/*.csv`: the output of `counting_script.py` (see below)
- `metrics/fragments.py`: helpers that read XML fragments (plain text + tag positions) and match tags
- `metrics/scores.py`: the metrics, one function per metric (tag accuracy, average distance, XML accuracy, XML matching)
- `metrics/check_cases.py`: checks the metrics on the test cases (see below)
- `metrics/test_data/`: temporary hand-made cases for checking the metrics (see its README)

## Running the scripts

### `counting_script.py`
Run it from the repository root (the folder this README is in):

```
python texts/counting_script.py
```

The script finds its files relative to its own folder (`texts/`), so it also works when run from any other folder.

On the first run it clones the Perseus Greek texts ([canonical-greekLit](https://github.com/PerseusDL/canonical-greekLit)) into `texts/canonical-greekLit/`. This folder is git-ignored, so it is never committed. Later runs reuse it.

It writes three CSV files to `texts/`:
- `greek_english_texts.csv`: one row per work that has both a Greek edition and an English translation, with all of its files and a GitHub link
- `greek_english_pairs.csv`: one row per Greek file/English translation pair (a work with 4 English translations gets 4 rows)
- `tei_tag_frequencies.csv`: statistics for each TEI tag, counted only inside `<text>` (the `<teiHeader>` metadata is skipped). Rows are sorted by `greek_with_text`, highest first. Columns:
  - `greek_count`: how often the tag appears in the Greek files
  - `greek_with_text`: how often it has text directly inside it (not only inside its child tags). Empty markers such as `<pb/>` and containers such as `<div>` get 0 or close to it
  - `greek_script_share`: share of that text written in Greek letters (0–1). A low value means the tag mostly holds Latin or English, e.g. editors' notes
  - `greek_inline_share`: share of occurrences found inside a `<p>` or `<l>`, i.e. in the middle of a sentence (0–1)
  - `english_count`, `english_with_text`: the same counts for the English translations

`texts/tei_tag_frequencies_prev.csv` is the previous version of `tei_tag_frequencies.csv`, kept for comparison. It counted whole files (including the `<teiHeader>`) and had a `total` column. It is not updated by the script.

At the end the script prints the 15 most frequent inline tags (tags with text and a `greek_inline_share` of at least 0.5). These are the candidates for the tag list.

### `check_cases.py`
Run it from the repository root:

```
python -m metrics.check_cases
```

(`-m` runs it as part of the `metrics` package, so it must be run from the repository root.)

It checks the tag-placement metrics in `metrics/scores.py`, from Zenkel et al. (2021): tag accuracy (share of tags in exactly the right place) and average distance (how many characters off they are), plus lists of misplaced, missing and extra tags and a score per tag type. It runs them on every case in `metrics/test_data/cases.json` and prints `PASS` or `FAIL` for each one. For a failed case it shows which tags were judged differently from the expected result, with the tag marked in the sentence (e.g. `"Theo.[</label>] We bring..."`), and the expected and actual scores. If the output is not valid XML or its text differs from the reference, it shows where.

It also checks the structure metrics from Hashimoto et al. (2019) on every case in `metrics/test_data/structure_cases.json`: XML accuracy (is the output valid XML?) and XML matching (does it have exactly the same tags as the input?). For a failed case it lists which tags are in the input but not the output, or the other way round.

## Using the metrics in your own code
The metrics are in `metrics/scores.py`, one function per metric. Import them from any script in the repository:

```python
from metrics.scores import tag_accuracy, average_distance, score
from metrics.scores import is_valid_xml, xml_accuracy, same_structure, xml_matching
```

Run that script **from the repository root with `-m`**, using dots instead of slashes and no `.py` (otherwise Python cannot find `metrics`):

```
python -m pipeline.translate        works
python pipeline/translate.py        ModuleNotFoundError: No module named 'metrics'
```

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

A score that cannot be computed is `None`: e.g. `tag_accuracy` when the output is not valid XML, or its text differs from the reference. What each metric means, with examples, is explained in `metrics/test_data/README.md`.

Example:

```python
from metrics.scores import tag_accuracy, average_distance, same_structure

ref = 'Then <name>Socrates</name> said.'
hyp = 'Then Socrates <name>said</name>.'
tag_accuracy(ref, hyp)        # 0.0
average_distance(ref, hyp)    # 7.0  (<name> is 9 characters off, </name> 5)

greek = '<said who="#Σωκράτης"><label>ΣΩ.</label> πάνυ γε.</said>'
output = '<said who="#Σωκράτης">Soc. Certainly.</said>'
same_structure(greek, output) # False: the <label> tag was lost
```

`is_valid_xml` and `same_structure` can also be used **inside the pipeline**, to check each translated passage straight away (e.g. log or retry when the output lost a tag).

To try the functions interactively, type `python` in the repository root and import them as above. If printing Greek text gives `UnicodeEncodeError: 'charmap' codec ...`, run `$env:PYTHONUTF8 = "1"` (PowerShell) once in that terminal first.
