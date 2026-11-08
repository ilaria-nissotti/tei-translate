
from pathlib import Path
from collections import Counter, defaultdict
import subprocess
import csv
import xml.etree.ElementTree as ET

# All paths are built from this script's folder (texts/), so the script
# reads and writes the same files no matter where it is run from.
HERE = Path(__file__).resolve().parent
repo = HERE / "canonical-greekLit"
texts_csv = HERE / "greek_english_texts.csv"
pairs_csv = HERE / "greek_english_pairs.csv"
tags_csv = HERE / "tei_tag_frequencies.csv"

if not repo.exists():
    subprocess.run([
        "git", "clone", "--depth", "1",
        "https://github.com/PerseusDL/canonical-greekLit.git",
        str(repo)
    ], check=True)

works = defaultdict(lambda: {"grc": [], "eng": []})

# Find all Greek and English XML files
for path in (repo / "data").rglob("*.xml"):
    parts = path.name.split(".")

    if len(parts) < 4:
        continue

    work_id = ".".join(parts[:2])
    edition = parts[2]

    if "-grc" in edition:
        works[work_id]["grc"].append(path)
    elif "-eng" in edition:
        works[work_id]["eng"].append(path)

# Only retain works available in BOTH languages
paired = {
    work_id: versions
    for work_id, versions in works.items()
    if versions["grc"] and versions["eng"]
}

def get_metadata(path):
    """Read author and title from the TEI header."""
    try:
        root = ET.parse(path).getroot()

        title = root.find(
            ".//{*}teiHeader/{*}fileDesc/"
            "{*}titleStmt/{*}title"
        )
        author = root.find(
            ".//{*}teiHeader/{*}fileDesc/"
            "{*}titleStmt/{*}author"
        )

        return (
            " ".join(title.itertext()).strip()
            if title is not None else "",
            " ".join(author.itertext()).strip()
            if author is not None else ""
        )
    except ET.ParseError:
        return "", ""

# Save one row per Greek/English file pair
# (a work with 1 Greek edition and 4 English translations gets 4 rows)
with open(pairs_csv, "w", newline="",
          encoding="utf-8") as f:

    writer = csv.writer(f)
    writer.writerow([
        "work_id",
        "author",
        "title",
        "greek_file",
        "english_file"
    ])

    for work_id, versions in sorted(paired.items()):
        for grc in sorted(versions["grc"]):
            title, author = get_metadata(grc)

            for eng in sorted(versions["eng"]):
                writer.writerow([
                    work_id,
                    author,
                    title,
                    grc.relative_to(repo).as_posix(),
                    eng.relative_to(repo).as_posix()
                ])

# Tags that hold a whole stretch of text: a paragraph or a verse line.
# A tag found inside one of these sits in the middle of a sentence
# ("inline"), so after translation it has to be placed in the right spot.
TEXT_BLOCKS = {"p", "l"}


def direct_text(elem):
    """Text written directly inside an element, not inside its children.

    For <p>Hello <name>Plato</name> world</p> this is "Hello world"
    for <p>, and "Plato" for <name>.
    """
    pieces = [elem.text or ""]
    pieces += [child.tail or "" for child in elem]
    return " ".join("".join(pieces).split())


def is_greek_letter(char):
    """True for Greek and Coptic (U+0370-03FF) and Greek Extended (U+1F00-1FFF)."""
    return "Ͱ" <= char <= "Ͽ" or "ἀ" <= char <= "῿"


# Count TEI tags in the matched texts.
# Only the <text> part of each file is counted: the <teiHeader> holds
# metadata (publisher, editor, ...) that is never translated.
counts = {"grc": Counter(), "eng": Counter()}     # all occurrences
with_text = {"grc": Counter(), "eng": Counter()}  # occurrences with direct text
inline = Counter()         # Greek files: occurrences inside a <p> or <l>
letters = Counter()        # Greek files: letters directly inside the tag
greek_letters = Counter()  # ... of which are Greek script


def count_element(elem, lang, inside_block):
    """Count one element and, recursively, everything inside it."""
    if not isinstance(elem.tag, str):
        return  # skip comments and processing instructions

    tag = elem.tag.split("}")[-1]
    text = direct_text(elem)

    counts[lang][tag] += 1
    if text:
        with_text[lang][tag] += 1

    if lang == "grc":
        if inside_block:
            inline[tag] += 1
        for char in text:
            if char.isalpha():
                letters[tag] += 1
                if is_greek_letter(char):
                    greek_letters[tag] += 1

    for child in elem:
        count_element(child, lang, inside_block or tag in TEXT_BLOCKS)


for versions in paired.values():
    for lang in ("grc", "eng"):
        for path in versions[lang]:
            try:
                root = ET.parse(path).getroot()
            except ET.ParseError:
                print("Invalid XML:", path)
                continue

            text_elem = root.find("{*}text")
            if text_elem is not None:
                count_element(text_elem, lang, inside_block=False)


def share(part, whole):
    """part / whole as a string with 2 decimals, or "" if whole is 0."""
    return f"{part / whole:.2f}" if whole else ""


# Save the tag counts. Tags that most often contain text in the Greek
# files come first (ties sorted by tag name so the file is identical on
# every computer).
all_tags = set(counts["grc"]) | set(counts["eng"])
ranked = sorted(
    all_tags,
    key=lambda tag: (-with_text["grc"][tag], -counts["grc"][tag], tag)
)

with open(tags_csv, "w", newline="",
          encoding="utf-8") as f:

    writer = csv.writer(f)
    writer.writerow([
        "tag",
        "greek_count",
        "greek_with_text",
        "greek_script_share",
        "greek_inline_share",
        "english_count",
        "english_with_text"
    ])

    for tag in ranked:
        writer.writerow([
            tag,
            counts["grc"][tag],
            with_text["grc"][tag],
            share(greek_letters[tag], letters[tag]),
            share(inline[tag], counts["grc"][tag]),
            counts["eng"][tag],
            with_text["eng"][tag]
        ])


# Save one row per unique work
with open(texts_csv, "w", newline="",
          encoding="utf-8") as f:

    writer = csv.writer(f)
    writer.writerow([
        "work_id",
        "author",
        "title",
        "greek_editions",
        "english_translations",
        "greek_files",
        "english_files",
        "github_url"
    ])

    for work_id, versions in sorted(paired.items()):
        greek_files = sorted(set(versions["grc"]))
        english_files = sorted(set(versions["eng"]))

        # Read metadata from the first Greek edition
        title, author = get_metadata(greek_files[0])

        # Build the GitHub link
        author_id, text_id = work_id.split(".")
        github_url = (
            "https://github.com/PerseusDL/"
            "canonical-greekLit/tree/master/data/"
            f"{author_id}/{text_id}"
        )

        writer.writerow([
            work_id,
            author,
            title,
            len(greek_files),
            len(english_files),
            "; ".join(
                p.relative_to(repo).as_posix()
                for p in greek_files
            ),
            "; ".join(
                p.relative_to(repo).as_posix()
                for p in english_files
            ),
            github_url
        ])

print(f"Found {len(paired)} unique bilingual works.")


for work_id, versions in sorted(paired.items()):
    title, author = get_metadata(versions["grc"][0])

    print(f"{author} — {title} [{work_id}]")
    print(f"  Greek editions: {len(versions['grc'])}")
    print(f"  English translations: {len(versions['eng'])}")

# Show the 15 most frequent inline tags: tags that contain text and are
# found inside a <p> or <l> in at least half of their Greek occurrences.
# These are the candidates for the tag list (see tei_tag_frequencies.csv
# for all tags).
inline_tags = [
    tag for tag in ranked
    if with_text["grc"][tag] and inline[tag] / counts["grc"][tag] >= 0.5
]

print("\nTop 15 inline tags in the Greek files:")
print(f"  {'tag':<10}{'with text':>10}{'Greek script':>14}{'inline':>8}")
for tag in inline_tags[:15]:
    print(
        f"  {tag:<10}{with_text['grc'][tag]:>10}"
        f"{share(greek_letters[tag], letters[tag]):>14}"
        f"{share(inline[tag], counts['grc'][tag]):>8}"
    )

print("\nSaved:")
print("  texts/greek_english_texts.csv")
print("  texts/greek_english_pairs.csv")
print("  texts/tei_tag_frequencies.csv")
