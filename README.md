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
- `metrics/placement_metrics.py`: tag-placement metrics, checked on the test cases (see below)
- `metrics/test_data/`: temporary hand-made cases for checking the tag-placement metrics (see its README)

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

### `placement_metrics.py`
Run it from the repository root:

```
python metrics/placement_metrics.py
```

It contains the tag-placement metrics from Zenkel et al. (2021): tag accuracy (share of tags in exactly the right place) and average distance (how many characters off they are), plus lists of misplaced, missing and extra tags and a score per tag type. It runs them on every case in `metrics/test_data/cases.json` and prints `PASS` or `FAIL` for each one. For a failed case it shows which tags were judged differently from the expected result, with the tag marked in the sentence (e.g. `"Theo.[</label>] We bring..."`), and the expected and actual scores. If the output is not valid XML or its text differs from the reference, it shows where.
