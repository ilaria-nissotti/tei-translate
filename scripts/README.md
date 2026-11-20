# Scripts

Utilities for building the data, the gold set and the experiments behind the project. None of
them is needed to translate a file: for that, see the [root README](../README.md).

Commands are shown from the repository root. Apart from the data scripts, they need the package
installed (`pip install -e .[dev]`). Every script has `--help`.

## Data (no install needed)

- `python scripts/data/count_tags.py`: clones Perseus into `data/raw/` and writes the list of
  Greek works with English translations (`data/catalog/`) and tag counts (`data/stats/`).
- `python scripts/data/build_dataset.py`: downloads those Greek/English pairs into `data/perseus/`
  and labels each work as prose, poetry or drama.
- `python scripts/data/count_perseus_tags.py`: tag counts over `data/perseus/` (needs
  `build_dataset.py` first), written to `data/stats/perseus_tag_frequencies_{greek,all}.csv`.

## Gold set

- `python scripts/gold/check_gold.py GREEK.xml GOLD.xml`: checks a gold English translation
  against its Greek source: runs the pipeline's validation checks, lists missing or extra tags per
  block, and flags Greek left untranslated outside kept elements. Run it before adding a file to
  `data/gold/grc-en/`.

## Experiments

These need `data/perseus/` and the `mt` extra; results go to `outputs/`.

- `compare_engines.py`: plain-text translation quality per engine (chrF, BLEU).
  `--reuse <run>` adds engines to an earlier run without re-running the others.
- `compare_spanwise.py`: whole-passage vs span-wise vs hybrid translation on the same passages.
- `bench_engine_threads.py`: speed and memory with few CPU threads (like the free HF Space).
- `check_schema_corpus.py`: runs the pipeline on every Greek file and checks the TEI schema.

## Evaluation

- `eval_translation.py --run outputs/compare/<run>`: chrF, BLEU and COMET per engine.
- `eval_placement.py --aligners none monotone sentence xlmr ugarit`: how well tags are placed,
  measured on the gold set (`data/gold/grc-en/`). The pipeline places the Greek tags into the
  gold English text, so only the tag positions can differ. Main score: strict accuracy (share of
  gold tags in exactly the right place; spaces and punctuation ignored).
- `eval_end_to_end.py --max-files 3 --max-blocks 40`: the whole pipeline on the gold set's Greek,
  compared with the gold English: validity, structure, chrF/COMET, Node-chrF.
