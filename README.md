# tei-translate
Translate TEI XML documents while preserving tag structure and meaning.

## Requirements
- Python 3 (the scripts only use the standard library, so no `pip install` is needed yet)
- `git` (used to download the Perseus texts)

## Repository layout
- `Essentials_Proposal.pdf`: project proposal
- `feedback_overview.md`: feedback on the proposal and the open decisions
- `proposed_tasks.md`: who does what
- `texts/counting_script.py`: finds the Perseus works that have both Greek and English versions and counts their TEI tags
- `texts/*.csv`: the output of `counting_script.py` (see below)

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
- `tei_tag_frequencies.csv`: how often each TEI tag appears in the Greek and English files, most frequent first