"""Evaluation metrics, one easy-to-call function per metric.

Tag placement (Zenkel et al. 2021):
- tag_accuracy: share of reference tags at exactly the right position in
  the output.
- average_distance: how many characters off the tags are, on average.
- score: both metrics at once, plus the lists of misplaced, missing and
  extra tags and a score per tag type.

Structure (Hashimoto et al. 2019):
- is_valid_xml / xml_accuracy: is the output valid XML? (one output / share
  of all outputs)
- same_structure / xml_matching: does the output have exactly the same tags
  as the input? (one output / share of all outputs)

What the metrics mean, worked examples, and what they leave out are
explained in metrics/test_data/README.md.

Usage (from any script in the repository, run from the repository root):

    from metrics.scores import tag_accuracy, average_distance, same_structure

    ref = 'Then <name>Socrates</name> said.'
    hyp = 'Then Socrates <name>said</name>.'
    tag_accuracy(ref, hyp)      # 0.0
    average_distance(ref, hyp)  # 7.0  (<name> 9 off, </name> 5 off)

    source = 'ὁ δὲ <name type="ethnic">Χῖος</name> <name type="person">Ἴων</name> ...'
    hyp = 'And <name type="person">Ion</name> of <name type="ethnic">Chios</name> ...'
    same_structure(source, hyp)  # True
"""

from metrics.fragments import read_fragment, match_tags, parse_fragment, structure_key


# ---------------------------------------------------------------------------
# Tag placement
# ---------------------------------------------------------------------------

def score(reference, hypothesis):
    """Compare the tags of a hypothesis with those of the reference.

    Both are XML fragments with the same text. Returns a dict with the
    fields described in metrics/test_data/README.md.
    """
    ref = read_fragment(reference)
    hyp = read_fragment(hypothesis)
    if ref is None:
        raise ValueError("the reference is not well-formed XML")
    ref_text, ref_tags = ref

    result = {
        "well_formed": hyp is not None,
        "same_text": hyp is not None and hyp[0] == ref_text,
        "reference_text": ref_text,
    }
    if not result["same_text"]:
        # Character positions cannot be compared: no placement scores.
        for field in ["reference_tag_count", "correct_count", "tag_accuracy",
                      "average_distance", "misplaced_tags", "missing_tags",
                      "extra_tags", "per_tag"]:
            result[field] = None
        return result

    pairs, missing, extra = match_tags(ref_tags, hyp[1])
    correct = [(r, h) for r, h in pairs if r[2] == h[2]]
    misplaced = [(r, h) for r, h in pairs if r[2] != h[2]]

    per_tag = {}
    for _, name, _ in ref_tags:
        per_tag.setdefault(name, {"correct": 0, "total": 0})["total"] += 1
    for (_, name, _), _ in correct:
        per_tag[name]["correct"] += 1

    distances = [abs(r[2] - h[2]) for r, h in pairs]

    result.update({
        "reference_tag_count": len(ref_tags),
        "correct_count": len(correct),
        # Missing tags count as wrong: divide by all reference tags.
        "tag_accuracy": len(correct) / len(ref_tags),
        # Only paired tags have a distance.
        "average_distance": sum(distances) / len(distances) if distances else None,
        "misplaced_tags": [
            {"tag": r[0], "reference_position": r[2],
             "hypothesis_position": h[2], "distance": abs(r[2] - h[2])}
            for r, h in misplaced
        ],
        "missing_tags": [{"tag": t[0], "reference_position": t[2]} for t in missing],
        "extra_tags": [{"tag": t[0], "hypothesis_position": t[2]} for t in extra],
        "per_tag": per_tag,
    })
    return result


def tag_accuracy(reference, hypothesis):
    """Share of reference tags at exactly the right position (0-1).

    None if the output is not valid XML or its text differs from the reference.
    """
    return score(reference, hypothesis)["tag_accuracy"]


def average_distance(reference, hypothesis):
    """Average number of characters the tags are off (0 = all in place).

    None if the output is not valid XML, its text differs from the
    reference, or no tag could be paired.
    """
    return score(reference, hypothesis)["average_distance"]


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def is_valid_xml(hypothesis):
    """True if the output is valid (well-formed) XML.

    Only checks that the XML is not broken (every tag closed, correct
    nesting, & written as &amp; ...). It does not check which tags there are.
    """
    return parse_fragment(hypothesis) is not None


def xml_accuracy(hypotheses):
    """Share of outputs that are valid XML (0-1). Hashimoto et al. (2019).

    hypotheses is a list of XML fragments. None if the list is empty.
    """
    if not hypotheses:
        return None
    valid = [is_valid_xml(hyp) for hyp in hypotheses]
    return sum(valid) / len(valid)


def same_structure(source, hypothesis):
    """True if the output has exactly the same tag structure as the input.

    The same tags, with the same attribute values, nested in the same way.
    Text is ignored, and so is the order of tags under the same parent
    (English word order differs from Greek). False if the output is not
    valid XML. The rules and examples are in metrics/test_data/README.md.
    """
    src = parse_fragment(source)
    if src is None:
        raise ValueError("the source is not well-formed XML")
    hyp = parse_fragment(hypothesis)
    if hyp is None:
        return False
    return structure_key(src) == structure_key(hyp)


def xml_matching(sources, hypotheses):
    """Share of outputs with the same tag structure as their input (0-1).

    Based on Hashimoto et al. (2019), but compared with the input instead of
    the reference. sources and hypotheses are lists of XML fragments in the
    same order (the 1st output belongs to the 1st input). None if empty.
    """
    if len(sources) != len(hypotheses):
        raise ValueError(f"{len(sources)} sources but {len(hypotheses)} hypotheses")
    if not hypotheses:
        return None
    same = [same_structure(src, hyp) for src, hyp in zip(sources, hypotheses)]
    return sum(same) / len(same)
