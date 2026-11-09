"""Tag-placement metrics (Zenkel et al. 2021), checked on hand-made test cases.

- Tag accuracy: share of reference tags at exactly the right position in
  the output.
- Average distance: how many characters off the tags are, on average.

A tag's position is the number of text characters before it. What the
metrics mean, a worked example, and what they leave out are explained in
metrics/test_data/README.md, section "The metrics".

Run from the repository root:

    python metrics/placement_metrics.py

The script scores every case in metrics/test_data/cases.json and prints
PASS or FAIL for each one. The rules (how text, positions and tags are
defined) are described in metrics/test_data/README.md.
"""

from pathlib import Path
import json
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
cases_file = HERE / "test_data" / "cases.json"


# ---------------------------------------------------------------------------
# Reading a fragment: plain text + tag positions
# ---------------------------------------------------------------------------

def tag_label(elem):
    """Tag name, plus the n attribute if it has one, e.g. 'milestone[n=216c]'."""
    n = elem.get("n")
    return elem.tag if n is None else f"{elem.tag}[n={n}]"


def read_fragment(fragment):
    """Split an XML fragment into its plain text and its tags.

    Returns (text, tags), or None if the fragment is not well-formed XML.
    Each tag is (label, tag_name, position), where position is the number
    of text characters before the tag. Whitespace is normalised: every run
    of spaces/line breaks counts as one space, leading and trailing spaces
    are dropped.

    Example: '<q>Hello</q> world' gives
        text = 'Hello world'
        tags = [('<q>', 'q', 0), ('</q>', 'q', 5)]
    """
    try:
        root = ET.fromstring(f"<root>{fragment}</root>")
    except ET.ParseError:
        return None

    chars = []
    tags = []

    def add_text(text):
        for char in text or "":
            if not char.isspace():
                chars.append(char)
            elif chars and chars[-1] != " ":
                chars.append(" ")

    def visit(elem):
        label = tag_label(elem)
        if len(elem) == 0 and not elem.text:
            # Empty element such as <milestone/>: one tag.
            tags.append((f"<{label}/>", elem.tag, len(chars)))
            return
        # Element with content: an opening and a closing tag.
        tags.append((f"<{label}>", elem.tag, len(chars)))
        add_text(elem.text)
        for child in elem:
            visit(child)
            add_text(child.tail)
        tags.append((f"</{label}>", elem.tag, len(chars)))

    add_text(root.text)
    for child in root:
        visit(child)
        add_text(child.tail)

    text = "".join(chars).rstrip()
    # A tag after a removed trailing space sits at the end of the text.
    tags = [(label, name, min(pos, len(text))) for label, name, pos in tags]
    return text, tags


# ---------------------------------------------------------------------------
# Matching reference tags to hypothesis tags
# ---------------------------------------------------------------------------

def match_positions(ref, hyp):
    """Pair two sorted lists of positions so the total distance is smallest.

    Pairs keep their order (the 1st paired ref with the 1st paired hyp, and
    so on), which is always optimal for positions on a line. If the lists
    have different lengths, the extra positions stay unpaired.
    Returns a list of (ref_index, hyp_index).
    """
    if len(ref) > len(hyp):
        return [(r, h) for h, r in match_positions(hyp, ref)]

    # cost[i][j]: smallest total distance pairing ref[:i] with some of hyp[:j]
    n, m = len(ref), len(hyp)
    INF = float("inf")
    cost = [[INF] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        cost[0][j] = 0
    for i in range(1, n + 1):
        for j in range(i, m + 1):
            skip = cost[i][j - 1]
            pair = cost[i - 1][j - 1] + abs(ref[i - 1] - hyp[j - 1])
            cost[i][j] = min(skip, pair)

    # Walk back through the table to recover the pairs.
    pairs = []
    i, j = n, m
    while i > 0:
        if cost[i][j] == cost[i][j - 1] and j > i:
            j -= 1
        else:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
    return pairs[::-1]


def match_tags(ref_tags, hyp_tags):
    """Pair reference and hypothesis tags that have the same label.

    First, tags at exactly the same position are paired (as many as
    possible, which maximises accuracy). The rest are paired so that the
    total distance is smallest. Returns (pairs, missing, extra).
    """
    pairs, missing, extra = [], [], []

    for label in {tag[0] for tag in ref_tags + hyp_tags}:
        ref = sorted((t for t in ref_tags if t[0] == label), key=lambda t: t[2])
        hyp = sorted((t for t in hyp_tags if t[0] == label), key=lambda t: t[2])

        # 1. Exact matches.
        remaining_hyp = list(hyp)
        remaining_ref = []
        for tag in ref:
            same = next((h for h in remaining_hyp if h[2] == tag[2]), None)
            if same:
                pairs.append((tag, same))
                remaining_hyp.remove(same)
            else:
                remaining_ref.append(tag)

        # 2. Closest matches for the rest.
        matched = match_positions([t[2] for t in remaining_ref],
                                  [t[2] for t in remaining_hyp])
        pairs += [(remaining_ref[r], remaining_hyp[h]) for r, h in matched]
        paired_r = {r for r, _ in matched}
        paired_h = {h for _, h in matched}
        missing += [t for i, t in enumerate(remaining_ref) if i not in paired_r]
        extra += [t for i, t in enumerate(remaining_hyp) if i not in paired_h]

    return pairs, missing, extra


# ---------------------------------------------------------------------------
# The metrics
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


# ---------------------------------------------------------------------------
# Checking the metrics on the test cases
# ---------------------------------------------------------------------------

def same_value(got, expected):
    """Compare a result with its expected value.

    Numbers may differ by 0.0001 (cases.json rounds to 4 decimals) and the
    order of the tag lists does not matter.
    """
    if isinstance(expected, float) and isinstance(got, (int, float)):
        return abs(got - expected) <= 1e-4
    if isinstance(expected, list) and isinstance(got, list):
        def key(item):
            return json.dumps(item, sort_keys=True)
        return sorted(got, key=key) == sorted(expected, key=key)
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
    def position_in_text(key):
        ref_pos = key[1]
        return ref_pos if ref_pos is not None else key[2]

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
    def accuracy(fields):
        return (f"{fields['tag_accuracy']:.0%} "
                f"({fields['correct_count']} of {fields['reference_tag_count']} tags correct)")

    def distance(fields):
        value = fields["average_distance"]
        return "-" if value is None else f"{value:.2f} characters"

    lines.append(f"{'':<18}{'expected':<36}got")
    lines.append(f"{'tag accuracy':<18}{accuracy(exp):<36}{accuracy(result)}")
    lines.append(f"{'average distance':<18}{distance(exp):<36}{distance(result)}")
    return lines


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
    print(f"\nFAIL  {case['id']}")
    print(f"      This case: {case['description']}\n")
    for line in explain_failure(case, result):
        print(f"      {line}" if line else "")
    print()

print(f"\n{len(cases) - failed} of {len(cases)} cases passed.")
