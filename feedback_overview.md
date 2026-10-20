## Feedback Overview: Problems & Solutions

**Scope is open-ended (Sina, Igli point 1; Scope: "at risk")**
- Problem: What features we implement is still an open question.
- Fix: Commit to the 3 handling classes (translate, keep, transliterate), a fixed list of 6-8 TEI elements, and one language per pair (Latin -> English for example). Move linking between original and translation for future work.

***OPTIONS Tag list** (which 6-8 TEI elements are in scope)*

- *A: `<p>`, `<l>`, `<q>`, `<foreign>`, `<persName>`, `<placeName>`, `<note>`, `<head>` (recommended, covers prose, verse, quotes, names, and notes)*
- *B: A, minus `<note>` and `<head>` (smaller, faster to label)*
- *C: Let the Perseus files decide: take the 8 most frequent elements in the chosen subset.*

**Evaluation isn't defined (Sina; Analysis: "Partial")**
- Problem: The proposal names metrics but not how they're scored.
- Fix: Define each measure:
    - Structural validity: pass/fail on well-formedness, TEI schema, and element/attribute comparison with the input.
    - Tag handling: a hand-labelled set of 50-100 snippets with expected behaviour per element, reported as accuracy per tag type.
    - Translation quality: chrF and COMET on translated spans against the Perseus scholarly translations.

**Only a single score (Analysis: "Partial")**
- Problem: Results would be one number, which hides where the tool fails.
- Fix: Add an error analysis grouped by element type and by document, plus a small human rating sample.

**Tag placement is unverified (Igli point 2)**
- Problem: It's unclear how we'll check that tags end up in the right place.
- Fix: Translate each text span inside its element and reinsert it there, so structure is kept by construction. Then verify with the structural checks in item 2. This avoids word alignement, which is the hardest part.

**Translation system and languages unspecified (Igli point 3; Method: "Partial")**
- Problem: No concrete system or language pair was named.
- Fix: Name on system (e.g., DeepL API, or other) and justify it in one sentence. Fix Latin -> English for example, with Greek as an extension.

***OPTIONS Translation system***

- *A: DeepL API (recommended for quality and for a direct comparison with the baseline; needs an API key and has a cost...)*
- *B: NLLB (open, reproducible, free to run, but likely weaker on Latin)*
- *C: OPUS-MT (open, lightweight, fast, but a smaller model)*
- *D: Large language model via API (flexible, but harder to reproduce exactly)*

***OPTIONS Language pair***
- *A: Latin -> English (recommended; the most scholarly translations are available)*
- *B: Greek -> English (fewer scholarly parallels in the Perseus subset to compare against)*
- *C: Both, with Latin first and Greek only if time allows.*

**Baseline is only implied (Baseline: "Yes", but worth tightening)**
- Problem: The comparison should be clearly the same segments under each system.
- Fix: Run DeepL and a whole-document baseline on the same segments as our pipeline, so results are directly comparable.

**Dataset not yet committed (Data accessible: "Partial")**
- Problem: Perseus is named, but the subset and the matching scholarly translations aren't chosen.
- Fix: Pick 5-10 Latin texts that have an English scholarly translation, list the files, and state the reason for our choice. Mention that other libraries are out of scope unless time allows.

**Scope vs. time budget (Scope: "at risk")**
- Problem: It's unclear whether the plan fits the 55 hours.
- Fix: Include three-person split (about 18 hours each) with a week 1 shared decisions time frame, so the workload is visible.