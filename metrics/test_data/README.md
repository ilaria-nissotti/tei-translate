# Test data for the tag-placement metrics (temporary)

Small hand-made cases for checking that the tag-placement metrics are computed correctly, before we use them on real output. Each case has a **reference** (tags in the correct place), a **hypothesis** (the tool's output) and the **expected** scores. A metric implementation should reproduce the expected values for every case. `metrics/placement_metrics.py` checks this: run `python metrics/placement_metrics.py` from the repository root.

The English text comes from real Perseus translations: Plato's *Sophist* 216a–d (`tlg0059.tlg007.perseus-eng2`) and *Republic* 327a–b (`tlg0059.tlg030.perseus-eng2`), shortened and with the editors' notes removed. Cases 06–07 are the example from Zenkel et al. (2021), Figure 3, so we can check that we reproduce the paper's numbers.

## Files
- `cases.json`: all cases, as one JSON list. Load it with `json.load(open("cases.json", encoding="utf-8"))`.

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
