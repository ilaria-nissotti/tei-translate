"""Check the metrics in scores.py on the hand-made test cases.

Run from the repository root:

    python -m metrics.check_cases

The script scores every case in metrics/test_data/ and prints PASS or FAIL
for each one:
- cases.json: tag placement (tag accuracy, average distance)
- structure_cases.json: structure (XML accuracy, XML matching)

For a failed case it explains, in words, how the result differs from the
expected one. The cases are described in metrics/test_data/README.md.
"""

from collections import Counter
from pathlib import Path
import json
import xml.etree.ElementTree as ET

from metrics.fragments import read_fragment, parse_fragment, tag_signature
from metrics.scores import score, is_valid_xml, xml_accuracy, same_structure, xml_matching

HERE = Path(__file__).resolve().parent
cases_file = HERE / "test_data" / "cases.json"
structure_cases_file = HERE / "test_data" / "structure_cases.json"


def as_sort_key(item):
    """A tag-list item as a string, so lists of dicts can be sorted."""
    return json.dumps(item, sort_keys=True)


def same_value(got, expected):
    """Compare a result with its expected value.

    Numbers may differ by 0.0001 (cases.json rounds to 4 decimals) and the
    order of the tag lists does not matter.
    """
    if isinstance(expected, float) and isinstance(got, (int, float)):
        return abs(got - expected) <= 1e-4
    if isinstance(expected, list) and isinstance(got, list):
        return sorted(got, key=as_sort_key) == sorted(expected, key=as_sort_key)
    return got == expected


def tag_verdicts(reference, fields):
    """What a result says about each tag, e.g. {('</label>', 5): ('misplaced', 8)}.

    Reference tags are keyed by (label, reference position) and get
    ('correct', None), ('misplaced', hypothesis position) or ('missing', None).
    Extra tags are keyed by (label, None) and get ('extra', hypothesis position).
    """
    verdicts = {(label, pos): ("correct", None)
                for label, _, pos in read_fragment(reference)[1]}
    for tag in fields["misplaced_tags"]:
        verdicts[(tag["tag"], tag["reference_position"])] = ("misplaced", tag["hypothesis_position"])
    for tag in fields["missing_tags"]:
        verdicts[(tag["tag"], tag["reference_position"])] = ("missing", None)
    for tag in fields["extra_tags"]:
        verdicts[(tag["tag"], None, tag["hypothesis_position"])] = ("extra", tag["hypothesis_position"])
    return verdicts


def describe(verdict):
    """A verdict in words."""
    kind, hyp_pos = verdict
    return {
        "correct": "in the right place",
        "misplaced": "in the wrong place",
        "missing": "missing from the output",
        "extra": "an extra tag (not in the reference)",
        None: "not there",
    }[kind]


def show_tag(text, pos, label, width=25):
    """The text around a position, with the tag shown in brackets.

    show_tag("Theo. We bring", 5, "</label>") gives '"Theo.[</label>] We bring"'.
    """
    before = text[max(0, pos - width):pos]
    after = text[pos:pos + width]
    start = "..." if pos > width else ""
    end = "..." if pos + width < len(text) else ""
    return f'"{start}{before}[{label}]{after}{end}"'


def position_in_text(key):
    """Where a tag-verdict key sits in the text, for sorting.

    Reference tags use their reference position; extra tags (no reference
    position) use their hypothesis position.
    """
    ref_pos = key[1]
    return ref_pos if ref_pos is not None else key[2]


def format_accuracy(fields):
    """Tag accuracy in words, e.g. '50% (1 of 2 tags correct)'."""
    return (f"{fields['tag_accuracy']:.0%} "
            f"({fields['correct_count']} of {fields['reference_tag_count']} tags correct)")


def format_distance(fields):
    """Average distance in words, e.g. '2.00 characters', or '-' if there is none."""
    value = fields["average_distance"]
    return "-" if value is None else f"{value:.2f} characters"


def explain_failure(case, result):
    """Lines explaining, in words, how the result differs from the expected one."""
    exp = case["expected"]
    lines = []

    if result["well_formed"] != exp["well_formed"]:
        lines.append(f"Is the output valid XML?  expected: {'yes' if exp['well_formed'] else 'no'}, "
                     f"got: {'yes' if result['well_formed'] else 'no'}")
        if not result["well_formed"]:
            try:
                ET.fromstring(f"<root>{case['hypothesis']}</root>")
            except ET.ParseError as error:
                line, column = error.position
                if line == 1:
                    column -= len("<root>")  # the fragment was wrapped in <root>
                problem = str(error).split(":")[0]
                lines.append(f"  XML error: {problem} (line {line}, character {column})")
                hyp_line = case["hypothesis"].splitlines()[line - 1]
                lines.append(f"  output near the error: {show_tag(hyp_line, column, '!')}")
    elif result["same_text"] != exp["same_text"]:
        lines.append(f"Does the output have the same text as the reference?  "
                     f"expected: {'yes' if exp['same_text'] else 'no'}, "
                     f"got: {'yes' if result['same_text'] else 'no'}")
        if not result["same_text"]:
            ref_text = result["reference_text"]
            hyp_text = read_fragment(case["hypothesis"])[0]
            first = next((i for i, (a, b) in enumerate(zip(ref_text, hyp_text)) if a != b),
                         min(len(ref_text), len(hyp_text)))
            lines.append(f"  first difference at character {first}:")
            lines.append(f"  reference: {show_tag(ref_text, first, '>')}")
            lines.append(f"  output:    {show_tag(hyp_text, first, '>')}")
    if result["reference_text"] != exp["reference_text"]:
        lines.append("The text without tags is different:")
        lines.append(f'  expected: "{exp["reference_text"]}"')
        lines.append(f'  got:      "{result["reference_text"]}"')
    if exp["tag_accuracy"] is None or result["tag_accuracy"] is None:
        return lines  # no placement scores to compare

    # Tag by tag: which tags are judged differently?
    text = result["reference_text"]
    expected = tag_verdicts(case["reference"], exp)
    got = tag_verdicts(case["reference"], result)

    for key in sorted(expected.keys() | got.keys(), key=position_in_text):
        want, have = expected.get(key, (None, None)), got.get(key, (None, None))
        if want == have:
            continue
        label, ref_pos = key[0], key[1]
        lines.append(f"Tag {label}")
        lines.append(f"  expected: {describe(want)}")
        lines.append(f"  got:      {describe(have)}")
        if ref_pos is not None:
            lines.append(f"  reference has it here:  {show_tag(text, ref_pos, label)}")
        hyp_pos = have[1] if have[1] is not None else want[1]
        if hyp_pos is not None:
            lines.append(f"  output has it here:     {show_tag(text, hyp_pos, label)}")
            if ref_pos is not None:
                lines.append(f"  that is {abs(hyp_pos - ref_pos)} characters off")
        lines.append("")

    # The scores that follow from it, in readable form.
    lines.append(f"{'':<18}{'expected':<36}got")
    lines.append(f"{'tag accuracy':<18}{format_accuracy(exp):<36}{format_accuracy(result)}")
    lines.append(f"{'average distance':<18}{format_distance(exp):<36}{format_distance(result)}")
    return lines


def print_failure(case, lines):
    """Print a FAIL line for a case, with its description and the explanation lines."""
    print(f"\nFAIL  {case['id']}")
    print(f"      This case: {case['description']}\n")
    for line in lines:
        print(f"      {line}" if line else "")
    print()


def check_placement_cases():
    """Check tag accuracy and average distance on cases.json. Returns (passed, total)."""
    cases = json.loads(cases_file.read_text(encoding="utf-8"))
    failed = 0

    for case in cases:
        result = score(case["reference"], case["hypothesis"])
        wrong = [field for field, expected in case["expected"].items()
                 if not same_value(result.get(field), expected)]

        if not wrong:
            print(f"PASS  {case['id']}")
            continue

        failed += 1
        print_failure(case, explain_failure(case, result))

    return len(cases) - failed, len(cases)


# ---------------------------------------------------------------------------
# Structure cases (XML accuracy, XML matching)
# ---------------------------------------------------------------------------

def tag_signatures(fragment):
    """Count the tags of a valid fragment by name and attributes (the <root> wrapper left out)."""
    root = parse_fragment(fragment)
    return Counter(tag_signature(elem) for elem in root.iter() if elem is not root)


def yes_no(value):
    """True/False as 'yes'/'no'."""
    return "yes" if value else "no"


def explain_structure_failure(case, valid, same):
    """Lines explaining how the structure result differs from the expected one."""
    exp = case["expected"]
    lines = []
    if valid != exp["valid_xml"]:
        lines.append(f"Is the output valid XML?  expected: {yes_no(exp['valid_xml'])}, got: {yes_no(valid)}")
    if same != exp["same_structure"]:
        lines.append(f"Same structure as the input?  expected: {yes_no(exp['same_structure'])}, "
                     f"got: {yes_no(same)}")
        if valid:
            source_tags = tag_signatures(case["greek"])
            output_tags = tag_signatures(case["hypothesis"])
            missing = source_tags - output_tags
            extra = output_tags - source_tags
            for signature, count in missing.items():
                lines.append(f"  in the input but not in the output: <{signature}> ({count}x)")
            for signature, count in extra.items():
                lines.append(f"  in the output but not in the input: <{signature}> ({count}x)")
            if not missing and not extra:
                lines.append("  the same tags are in both, so they must be nested differently")
    return lines


def check_structure_cases():
    """Check the structure metrics on structure_cases.json. Returns (passed, total).

    Each case checks is_valid_xml and same_structure. Then xml_accuracy and
    xml_matching over all cases are checked against the share of expected
    True values.
    """
    cases = json.loads(structure_cases_file.read_text(encoding="utf-8"))
    failed = 0

    for case in cases:
        valid = is_valid_xml(case["hypothesis"])
        same = same_structure(case["greek"], case["hypothesis"])
        if valid == case["expected"]["valid_xml"] and same == case["expected"]["same_structure"]:
            print(f"PASS  {case['id']}")
            continue
        failed += 1
        print_failure(case, explain_structure_failure(case, valid, same))

    # The corpus-level scores: the share of expected True values.
    hypotheses = [case["hypothesis"] for case in cases]
    sources = [case["greek"] for case in cases]
    corpus_checks = [
        ("xml_accuracy", xml_accuracy(hypotheses),
         sum(case["expected"]["valid_xml"] for case in cases) / len(cases)),
        ("xml_matching", xml_matching(sources, hypotheses),
         sum(case["expected"]["same_structure"] for case in cases) / len(cases)),
    ]
    for name, got, expected in corpus_checks:
        if same_value(got, expected):
            print(f"PASS  {name} over all cases = {got:.2f}")
        else:
            failed += 1
            print(f"\nFAIL  {name} over all cases: expected {expected:.2f}, got {got:.2f}\n")

    total = len(cases) + len(corpus_checks)
    return total - failed, total


def main():
    print("Tag placement (cases.json)")
    placement_passed, placement_total = check_placement_cases()
    print(f"\n{placement_passed} of {placement_total} cases passed.")

    print("\nStructure (structure_cases.json)")
    structure_passed, structure_total = check_structure_cases()
    print(f"\n{structure_passed} of {structure_total} checks passed.")

    passed = placement_passed + structure_passed
    total = placement_total + structure_total
    print(f"\nAll together: {passed} of {total} passed.")


if __name__ == "__main__":
    main()
