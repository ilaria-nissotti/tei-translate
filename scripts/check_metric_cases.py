"""Check the metrics in scores.py on the hand-made test cases.

Needs the package installed (pip install -e .). Run:

    python scripts/check_metric_cases.py

The script scores every case in tests/fixtures/metrics/ and prints PASS or FAIL
for each one:
- cases.json: tag placement (tag accuracy, average distance)
- structure_cases.json: structure (XML accuracy, XML matching)
- translation_cases.json: removing tags, chrF and BLEU

For a failed case it explains, in words, how the result differs from the
expected one. The cases are described in tests/fixtures/metrics/README.md.
"""

from collections import Counter
from pathlib import Path
import json
import xml.etree.ElementTree as ET

from sacrebleu.metrics import BLEU, CHRF

from tei_translate.metrics.fragments import read_fragment, parse_fragment, tag_signature, strip_tags
from tei_translate.metrics.scores import score, is_valid_xml, xml_accuracy, same_structure, xml_matching
from tei_translate.metrics.translation_scores import chrf, bleu, reference_streams

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "metrics"
cases_file = FIXTURES / "cases.json"
structure_cases_file = FIXTURES / "structure_cases.json"
translation_cases_file = FIXTURES / "translation_cases.json"


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


# ---------------------------------------------------------------------------
# Translation cases (strip_tags, chrF, BLEU)
# ---------------------------------------------------------------------------

def report(passed, name, details=""):
    """Print PASS or FAIL for a named check (with details on failure). Returns 1 if it failed."""
    if passed:
        print(f"PASS  {name}")
        return 0
    print(f"\nFAIL  {name}\n      {details}\n")
    return 1


def raises_value_error(function, *arguments):
    """True if calling function(*arguments) raises a ValueError."""
    try:
        function(*arguments)
    except ValueError:
        return True
    return False


def padded_reference_texts(cases):
    """The cases' plain reference texts in sacrebleu's layout, padded with None.

    Written separately from translation_scores.reference_streams, so the
    check does not just repeat the code it is checking.
    """
    most = max(len(case["reference_texts"]) for case in cases)
    streams = [[] for _ in range(most)]
    for case in cases:
        texts = case["reference_texts"] + [None] * (most - len(case["reference_texts"]))
        for k in range(most):
            streams[k].append(texts[k])
    return streams


def check_translation_cases():
    """Check strip_tags, chrf and bleu on translation_cases.json. Returns (passed, total).

    chrF and BLEU themselves come from sacrebleu and are not recomputed by
    hand. What is checked is our part: that tags are removed correctly
    (also from broken XML), that several references are passed correctly,
    and that the result equals sacrebleu on the hand-written plain texts.
    """
    cases = json.loads(translation_cases_file.read_text(encoding="utf-8"))
    failed = 0
    total = 0

    # 1. strip_tags gives the hand-written plain text, for every hypothesis and reference.
    for case in cases:
        total += 1
        got = [strip_tags(ref) for ref in case["references"]] + [strip_tags(case["hypothesis"])]
        want = case["reference_texts"] + [case["hypothesis_text"]]
        wrong = [(w, g) for w, g in zip(want, got) if w != g]
        details = "; ".join(f'expected "{w}", got "{g}"' for w, g in wrong)
        failed += report(not wrong, f"strip_tags  {case['id']}", details)

    # 2. The layout for sacrebleu, on a small hand-written example.
    total += 1
    got = reference_streams([["A1", "A2"], "B1"])
    want = [["A1", "B1"], ["A2", None]]
    failed += report(got == want, "reference_streams  [['A1', 'A2'], 'B1'] -> [['A1', 'B1'], ['A2', None]]",
                     f"got {got}")

    # 3. chrF and BLEU on the XML equal sacrebleu on the plain texts.
    # A passage with one reference is passed as a string, with several as a list,
    # so both forms are checked.
    references = [case["references"][0] if len(case["references"]) == 1 else case["references"]
                  for case in cases]
    hypotheses = [case["hypothesis"] for case in cases]
    hyp_texts = [case["hypothesis_text"] for case in cases]
    ref_streams = padded_reference_texts(cases)
    for name, function, metric in [("chrf", chrf, CHRF()), ("bleu", bleu, BLEU())]:
        total += 1
        got = function(references, hypotheses)
        want = metric.corpus_score(hyp_texts, ref_streams).score
        failed += report(same_value(got, want),
                         f"{name} over all cases = {got:.2f} (same as sacrebleu on the plain texts)",
                         f"expected {want:.4f}, got {got:.4f}")

    # 4. Several references (case 07), compared with each reference on its own.
    # chrF scores each passage against its best-matching reference, so it must
    # equal the best single-reference score. BLEU lets n-grams match in any
    # reference, so it must be at least as high as the best single one.
    thuc = next(case for case in cases if len(case["references"]) > 1)
    hyp = [thuc["hypothesis"]]
    chrf_all = chrf([thuc["references"]], hyp)
    chrf_best = max(chrf([ref], hyp) for ref in thuc["references"])
    bleu_all = bleu([thuc["references"]], hyp)
    bleu_best = max(bleu([ref], hyp) for ref in thuc["references"])
    total += 2
    failed += report(same_value(chrf_all, chrf_best),
                     f"chrf with 3 references ({chrf_all:.2f}) = best single reference ({chrf_best:.2f})",
                     "chrF should use the best-matching reference")
    failed += report(bleu_all >= bleu_best,
                     f"bleu with 3 references ({bleu_all:.2f}) >= best single reference ({bleu_best:.2f})",
                     "more references should never lower BLEU")

    # 5. Wrong input is refused, and an empty test set gives None.
    checks = [
        (raises_value_error(chrf, ["a reference"], []), "different list lengths raise an error"),
        (raises_value_error(chrf, [[]], ["a hypothesis"]), "a passage without reference raises an error"),
        (chrf([], []) is None and bleu([], []) is None, "an empty test set gives None"),
    ]
    for passed, name in checks:
        total += 1
        failed += report(passed, name)

    return total - failed, total


def main():
    print("Tag placement (cases.json)")
    placement_passed, placement_total = check_placement_cases()
    print(f"\n{placement_passed} of {placement_total} cases passed.")

    print("\nStructure (structure_cases.json)")
    structure_passed, structure_total = check_structure_cases()
    print(f"\n{structure_passed} of {structure_total} checks passed.")

    print("\nTranslation (translation_cases.json)")
    translation_passed, translation_total = check_translation_cases()
    print(f"\n{translation_passed} of {translation_total} checks passed.")

    passed = placement_passed + structure_passed + translation_passed
    total = placement_total + structure_total + translation_total
    print(f"\nAll together: {passed} of {total} passed.")


if __name__ == "__main__":
    main()
