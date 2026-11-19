# Test data for the metrics (temporary)

Small hand-made cases for checking that the metrics are computed correctly, before we use them on real output. A metric implementation should reproduce the expected values for every case. `tests/test_metrics.py` checks this for the metrics in `src/tei_translate/metrics/`, with one test per case: run `pytest` from the repository root (after `pip install -e .[dev]`).

There are three sets of cases:
- `cases.json`: **tag placement** (tag accuracy, average distance). Described in the first part of this file.
- `structure_cases.json`: **structure** (XML accuracy, XML matching). Described in [Structure cases](#structure-cases-structure_casesjson) below.
- `translation_cases.json`: **removing tags, chrF and BLEU**. Described in [Translation cases](#translation-cases-translation_casesjson) below.

# Tag-placement cases (`cases.json`)

Each case has a **reference** (tags in the correct place), a **hypothesis** (the tool's output) and the **expected** scores.

The English text comes from real Perseus translations: Plato's *Sophist* 216a–d (`tlg0059.tlg007.perseus-eng2`) and *Republic* 327a–b (`tlg0059.tlg030.perseus-eng2`), shortened and with the editors' notes removed. Cases 06–07 are the example from Zenkel et al. (2021), Figure 3, so we can check that we reproduce the paper's numbers.

## The metrics
Both metrics come from Zenkel et al. (2021), "Automatic Bilingual Markup Transfer". They compare where each tag is in the output (the hypothesis) with where it is in the reference. They only work when both have exactly the same text, so that positions can be compared.

**Position of a tag:** remove all tags and count the characters of text before the tag. In `<q>Hello</q> world`, `<q>` is at position 0 and `</q>` at position 5. An element with content has two tags (opening and closing), each with its own position; an empty element such as `<milestone/>` has one.

**Tag accuracy:** the share of reference tags that are at exactly the same position in the output.

```
tag accuracy = tags at the right position / all tags in the reference
```

It answers "how many tags would someone have to fix by hand?". A tag is either right or wrong: one character off counts the same as fifty.

**Average distance:** for each tag, how many characters its position in the output is from its position in the reference, averaged over all tags.

```
average distance = sum of |reference position - output position| / number of tags
```

It answers "how far off are the tags?". 0 means every tag is in the right place; a higher number means the tags are further away.

**Why both:** two outputs can have the same accuracy but be wrong in very different ways. The example from the paper (Figure 3, our cases 06 and 07):

| | Sentence | `<b>` | `</b>` | Accuracy | Distance |
|---|---|---|---|---|---|
| Reference | `<b>But this</b> is not what happens.` | 0 | 8 | | |
| Output 1 | `But <b>this</b> is not what happens.` | 4 | 8 | 1 of 2 = 50% | (4 + 0) / 2 = **2** |
| Output 2 | `<b>But this is not what happens</b>.` | 0 | 28 | 1 of 2 = 50% | (0 + 20) / 2 = **10** |

Both have one tag right and one wrong, so both score 50% accuracy. But output 1 is off by one word and output 2 by most of the sentence, which only the distance shows.

**What each metric leaves out:**
- **Missing tags** (in the reference but not in the output) count as wrong in accuracy, but are left out of the distance, because they have no position to measure.
- **Extra tags** (in the output but not in the reference) change neither metric. They are listed separately in `extra_tags`.
- **Broken XML or changed text:** neither metric can be computed (`null`).

So always read the two scores together with the lists of misplaced, missing and extra tags.

## Files
- `cases.json`: all tag-placement cases, as one JSON list. Load it with `json.load(open("cases.json", encoding="utf-8"))`.
- `structure_cases.json`: all structure cases, in the same format (see [Structure cases](#structure-cases-structure_casesjson)).

## Fields of a case
| Field | Meaning |
|---|---|
| `id` | short name, numbered |
| `group` | `correct`, `paper_check`, `placement`, `missing_extra` or `structure` (see below) |
| `description` | what is wrong (or right) in the hypothesis |
| `source` | where the text comes from |
| `greek` | the matching Greek passage, for context only (not used in scoring) |
| `reference` | XML fragment with the tags in the correct place |
| `hypothesis` | XML fragment to score |
| `note` | only on debatable cases |
| `expected` | the scores a correct implementation should produce (see below) |

## Fields of `expected`
| Field | Meaning |
|---|---|
| `well_formed` | the hypothesis is valid XML |
| `same_text` | the hypothesis has exactly the same text as the reference once tags are removed |
| `reference_text` | the reference text without tags, after normalising whitespace. Positions count characters in this string |
| `reference_tag_count` | number of tags in the reference |
| `correct_count` | reference tags at exactly the right position |
| `tag_accuracy` | `correct_count / reference_tag_count` (Zenkel et al.) |
| `average_distance` | mean distance in characters between each matched reference tag and its hypothesis tag (Zenkel et al.) |
| `misplaced_tags` | every matched tag that is in the wrong place, with both positions |
| `missing_tags` | reference tags that do not appear in the hypothesis |
| `extra_tags` | hypothesis tags that do not appear in the reference |
| `per_tag` | correct / total per tag name, to see which tag types fail |

If the hypothesis is not well-formed, or its text differs from the reference, the placement scores are `null`: character positions cannot be compared.

## Groups
| Group | Cases | What they test |
|---|---|---|
| `correct` | 01–05 | should all give accuracy 1.0 and distance 0, including when only the XML formatting differs (case 04) |
| `paper_check` | 06–07 | must give 50% / 2.0 and 50% / 10.0, as in the paper |
| `placement` | 08–16 | tags in the wrong place: span too wide or too short, wrong word, milestone moved, milestones swapped, nesting changed, several errors at once |
| `missing_extra` | 17–20 | tags lost, added or duplicated |
| `structure` | 21–22 | broken XML, and changed wording (no placement score possible) |

## How the expected values were computed
These are choices. Change them if the team decides otherwise, and update the expected values.

1. **Text and positions.** All tags are removed. Every run of whitespace (spaces, line breaks) becomes one space, and leading and trailing whitespace is removed. A tag's position is the number of characters of this text that come before it.
2. **Tags.** An element with content counts as two tags: an opening tag at its start and a closing tag at its end. An element with no content (`<milestone/>`, `<pb/>`, and also `<milestone></milestone>`) counts as one tag.
3. **Labels.** Tags are matched by label: the tag name plus its `n` attribute if it has one, e.g. `milestone[n=216c]`. Other attributes are ignored. Using `n` means two swapped milestones are detected (case 13). Zenkel et al. use the tag name only.
4. **Matching.** When the same label appears more than once, reference and hypothesis tags are paired so that as many as possible are exactly right, then so that the total distance is as small as possible (following Zenkel et al.). Unpaired reference tags are *missing*; unpaired hypothesis tags are *extra*.
5. **Missing tags count as wrong** in `tag_accuracy` (the denominator is all reference tags). They are left out of `average_distance`, since they have no position.
6. **Extra tags** do not change `tag_accuracy`. They are only listed in `extra_tags`.

## Debatable case
- **15**: a milestone on the other side of a space (`all, <milestone/>I` vs `all,<milestone/> I`) counts as 1 character off. We may want to ignore whitespace when comparing positions, so that this counts as correct.

## Adding a case
Copy an existing case, change `reference`/`hypothesis`, and work out `expected` by hand with the rules above: write out `reference_text` and count characters to each tag.

# Structure cases (`structure_cases.json`)

Cases for the two structure metrics from Hashimoto et al. (2019), "A High-Quality Multilingual Dataset for Structured Documentation Translation". Unlike tag accuracy, they work on any output, even when its text differs from the reference.

The text comes from real Perseus files: Plato's *Sophist* 216a–d, *Republic* 327a–b (shortened) and Athenaeus' *Deipnosophists* 1.3f (`tlg0008.tlg001`, with the long `key` attributes of `<name>` left out for readability). The Greek is the input; the English is the Perseus translation, with the tags the way our tool should output them.

## The metrics
**XML accuracy:** is the output valid XML? Every tag closed, tags correctly nested, `&` written as `&amp;`, and so on. It does not check which tags there are.

```
xml_accuracy = valid outputs / all outputs
```

**XML matching:** does the output have exactly the same tag structure as the input?

```
xml_matching = outputs with the same structure as their input / all outputs
```

In code: `is_valid_xml(hyp)` and `same_structure(source, hyp)` judge one output (True/False); `xml_accuracy(hyps)` and `xml_matching(sources, hyps)` give the share over a list of outputs.

## Rules for "same structure"
These are choices. Change them if the team decides otherwise, and update the expected values.

1. **Compared with the input, not the reference.** Our tool should keep exactly the tags of the Greek input. The Perseus English translations often have different tags, e.g. a `<placeName>` the Greek does not have (case 12). Hashimoto et al. compare with the reference, but in their data the reference has the same tags as the input.
2. **Same tags, same nesting.** Every element in the input must be in the output, under the same parent element, and nothing may be added. A lost, extra, duplicated, renamed or re-nested tag makes it different (cases 09–13, 16, 17).
3. **Same attributes, same values.** Our tool copies attributes unchanged, so a translated value (`who="#Θεόδωρος"` → `"#Theodorus"`, case 14) or a lost attribute (case 15) makes it different.
4. **Text is ignored.** Only the tags are compared. Where a tag sits in the text, and which words it contains, are measured by tag accuracy, average distance and Node-chrF (cases 02, 08).
5. **The order of tags under the same parent is ignored.** English word order differs from Greek: "ὁ Χῖος Ἴων" becomes "Ion of Chios", so two name tags change places (case 06). The cost: two swapped milestones also count as the same structure (case 07). That error is caught by tag accuracy (tag-placement case 13), but not by XML matching.
6. **Formatting is ignored.** Line breaks, attribute order and `<milestone></milestone>` vs `<milestone/>` are the same XML (case 03).
7. **Invalid XML** never has the same structure (cases 18–20).

## Fields of a case
| Field | Meaning |
|---|---|
| `id`, `description`, `source`, `note` | as in `cases.json` |
| `group` | `same`, `different` or `invalid` (see below) |
| `greek` | the Greek input. Unlike in `cases.json`, it is used in scoring: XML matching compares the output with it |
| `hypothesis` | the English output to score |
| `expected.valid_xml` | `is_valid_xml(hypothesis)` should give this |
| `expected.same_structure` | `same_structure(greek, hypothesis)` should give this |

## Groups
| Group | Cases | What they test |
|---|---|---|
| `same` | 01–08 | same structure, including moved tags, formatting differences, reordered tags and an emptied tag |
| `different` | 09–17 | valid XML, but a tag lost, duplicated, added, renamed, re-nested, or an attribute changed or lost; and plain text with all tags removed |
| `invalid` | 18–20 | not valid XML: crossing tags, an unclosed tag, a bare `&` |

Over all 20 cases, `xml_accuracy` should be 17/20 = **0.85** and `xml_matching` 8/20 = **0.40**. `tests/test_metrics.py` checks these too.

## Adding a case
Copy an existing case, change `greek`/`hypothesis`, and decide `expected` with the rules above.

# Translation cases (`translation_cases.json`)

Cases for removing tags (`strip_tags`) and for the translation metrics chrF and BLEU (`src/tei_translate/metrics/translation_scores.py`). chrF and BLEU are computed by the sacrebleu library, so their values are **not** worked out by hand. The cases check our own part instead:

1. **Removing tags.** `strip_tags` must turn each reference and hypothesis into the hand-written plain text in `reference_texts` / `hypothesis_text`: tags removed, whitespace normalised, `&amp;` decoded to `&`.
2. **Same as sacrebleu.** `chrf` and `bleu` on the XML must give exactly the same score as sacrebleu on the hand-written plain texts. So tags make no difference to the score.
3. **Several references.** Case 07 has three translations of the same passage. chrF must equal the score against the best single reference (it scores each passage against its best-matching reference); BLEU must be at least as high as against any single reference (words can match in any of them).
4. **Wrong input.** Lists of different length, or a passage without reference, raise an error; an empty test set gives `None`.

## Rules for removing tags
- **Valid XML:** the text is exactly the text the tag-placement metrics use (`read_fragment`): all tags removed, every run of whitespace becomes one space, leading and trailing whitespace dropped. Empty tags such as `<milestone/>` and `<s/>` add no text.
- **Not valid XML:** best effort. Everything of the form `<...>` is removed with a regular expression, entities are decoded and whitespace normalised the same way (cases 04, 05). The translation can still be scored; that the XML is broken is reported by XML accuracy, so it is not counted twice.
- **Notes are not removed.** `strip_tags` keeps the text of every element, including `<note>`. See the open question below.

## Fields of a case
| Field | Meaning |
|---|---|
| `id`, `description`, `source` | as in `cases.json` |
| `references` | one or more reference translations of the passage (XML) |
| `hypothesis` | the output to score (XML, possibly broken) |
| `reference_texts` | the hand-written plain text of each reference, in the same order |
| `hypothesis_text` | the hand-written plain text of the hypothesis |

## Cases
| Case | What it tests |
|---|---|
| 01 | tags in both reference and hypothesis |
| 02 | an empty milestone and line breaks |
| 03 | `&amp;` in valid XML becomes `&` |
| 04 | a bare `&` (not valid XML): same text as case 03 |
| 05 | crossing tags (not valid XML): the words are still recovered |
| 06 | a plain-text hypothesis without any tags |
| 07 | three reference translations (Thucydides 1.1.1: Crawley, Hobbes, C. F. Smith), one with `<s/>` markers and line breaks as in the real Perseus file |

## Open question: editors' notes
`<note>` elements (the editors' notes, mostly in Latin) are copied unchanged into our output, but the Perseus English files have their own, different notes. If whole passages with notes are scored, the notes would count as "translation" in chrF and BLEU. Before scoring real output, decide whether to remove `<note>` elements (with their content) first.
