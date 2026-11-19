"""Helpers for reading XML fragments and matching their tags.

These functions do the work before any scoring: they parse an XML
fragment, turn it into plain text plus tag positions, pair the tags of a
reference with the tags of a hypothesis, and describe its tag structure.
The metrics themselves are in scores.py.

A tag's position is the number of text characters before it. The rules
(how text, positions and tags are defined) are described in
tests/fixtures/metrics/README.md, section "The metrics".
"""

import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# Parsing a fragment
# ---------------------------------------------------------------------------

def parse_fragment(fragment):
    """Parse an XML fragment. Returns its root element, or None if it is not valid XML.

    A fragment can have several top-level elements and text outside them
    (e.g. 'ὁ δὲ <name>Χῖος</name> ...'), so it is wrapped in a <root>
    element before parsing. The returned element is that <root>.
    """
    try:
        return ET.fromstring(f"<root>{fragment}</root>")
    except ET.ParseError:
        return None


# ---------------------------------------------------------------------------
# Reading a fragment: plain text + tag positions
# ---------------------------------------------------------------------------

def tag_label(elem):
    """Tag name, plus the n attribute if it has one, e.g. 'milestone[n=216c]'."""
    n = elem.get("n")
    return elem.tag if n is None else f"{elem.tag}[n={n}]"


def add_text(text, chars):
    """Append the characters of text to the list chars, normalising whitespace.

    Every run of spaces/line breaks becomes one space, and no space is
    added at the very start. text may be None (an element without text).
    """
    for char in text or "":
        if not char.isspace():
            chars.append(char)
        elif chars and chars[-1] != " ":
            chars.append(" ")


def add_element(elem, chars, tags):
    """Add an element's tags to the list tags and its text to the list chars.

    Goes through the element's children too. Each tag gets the position
    len(chars) at the moment it is reached, i.e. the number of text
    characters before it.
    """
    label = tag_label(elem)
    if len(elem) == 0 and not elem.text:
        # Empty element such as <milestone/>: one tag.
        tags.append((f"<{label}/>", elem.tag, len(chars)))
        return
    # Element with content: an opening and a closing tag.
    tags.append((f"<{label}>", elem.tag, len(chars)))
    add_text(elem.text, chars)
    for child in elem:
        add_element(child, chars, tags)
        add_text(child.tail, chars)
    tags.append((f"</{label}>", elem.tag, len(chars)))


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
    root = parse_fragment(fragment)
    if root is None:
        return None

    chars = []
    tags = []
    add_text(root.text, chars)
    for child in root:
        add_element(child, chars, tags)
        add_text(child.tail, chars)

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
# Tag structure
# ---------------------------------------------------------------------------

def structure_key(elem):
    """The tag structure of an element, as a value that can be compared with ==.

    Two elements have the same key when they have the same tag name, the
    same attributes with the same values, and children with the same keys.
    Text is ignored, and so is the order of the children: English word
    order differs from Greek, so tags under the same parent may change order.

    Example: <said who="#A"><label>X</label> text</said> gives
        ('said', (('who', '#A'),), (('label', (), ()),))
    """
    attributes = tuple(sorted(elem.attrib.items()))
    children = tuple(sorted(structure_key(child) for child in elem))
    return (elem.tag, attributes, children)


def tag_signature(elem):
    """An element's tag name and attributes as text, e.g. 'milestone n="216c" unit="section"'.

    Used to list which tags differ between two fragments.
    """
    attributes = " ".join(f'{name}="{value}"' for name, value in sorted(elem.attrib.items()))
    return f"{elem.tag} {attributes}" if attributes else elem.tag
