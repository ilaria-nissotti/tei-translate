# Task Division

## Person A: Pipeline and TEI handling
- Parse TEI XML and extract text spans per element
- Implement handling rules: translate, keep, transliterate
- Reinsert translated text into the original structure
- Validate output: well-formed XML, TEI schema, same structure as input
- Build the command-line entry point

## Person B: Translation and transliteration
- Set up the translation system (e.g., DeepL API or NLLB) for Latin→English
- Build the `translate(spans)` function, respecting the keep rule
- Build the transliteration step for names and places
- Build the baseline (whole-document translation, DeepL/Google on the same segments)
- Write translation metrics (chrF, COMET)

## Person C: Evaluation and data
- Select the Perseus TEI files and document the choice
- Hand-label the test set (50–100 snippets) and a list of 30–50 names with reference transliterations
- Write the evaluation script (tag accuracy, transliteration accuracy, structural pass/fail)
- Run the error analysis and collect a sample for human rating

## Shared (all three, week 1)
- Agree on the tag list (6–8 elements) and the handling rule for each
- Define the output contract and the labelled test set format
- Fix the translation system and language pair
- Set up the repository and folder layout
