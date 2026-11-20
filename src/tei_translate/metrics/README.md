# Metrics

```python
from tei_translate.metrics.scores import (tag_accuracy, average_distance, score,
    is_valid_xml, xml_accuracy, same_structure, xml_matching)
from tei_translate.metrics.translation_scores import chrf, bleu, node_chrf, node_chrf_corpus
from tei_translate.metrics.comet_score import comet          # needs the comet extra
```

Inputs are XML fragments as strings. The reference (or Greek input) always comes first.

| Function | Gives |
|---|---|
| `tag_accuracy(ref, hyp)` | share of tags in the right place (0–1); text must be the same in both |
| `average_distance(ref, hyp)` | how many characters the tags are off |
| `score(ref, hyp)` | both, plus misplaced/missing/extra tags and a score per tag type |
| `is_valid_xml(hyp)`, `xml_accuracy(hyps)` | is the output valid XML / share that is |
| `same_structure(src, hyp)`, `xml_matching(srcs, hyps)` | same tags as the input / share that has |
| `chrf(refs, hyps)`, `bleu(refs, hyps)` | corpus score (0–100), tags removed; a reference can be a list |
| `node_chrf(ref, hyp)` | are the right words inside each tag? |
| `comet(srcs, refs, hyps)` | COMET, tags removed |

`chrf` and `bleu` score the whole test set at once (don't average per-passage scores). A score
that can't be computed is `None`.

```python
tag_accuracy('Then <name>Socrates</name> said.', 'Then Socrates <name>said</name>.')  # 0.0
```
