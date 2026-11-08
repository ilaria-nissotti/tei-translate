
from pathlib import Path
from collections import Counter, defaultdict
import subprocess
import csv
import xml.etree.ElementTree as ET

repo = Path("canonical-greekLit")

if not repo.exists():
    subprocess.run([
        "git", "clone", "--depth", "1",
        "https://github.com/PerseusDL/canonical-greekLit.git"
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

# Save a complete catalog of matching texts
with open("greek_english_texts.csv", "w", newline="",
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

# Count TEI tags in the matched texts
counts = {"grc": Counter(), "eng": Counter()}

for versions in paired.values():
    for lang in ("grc", "eng"):
        for path in versions[lang]:
            try:
                root = ET.parse(path).getroot()
                for elem in root.iter():
                    tag = elem.tag.split("}")[-1]
                    counts[lang][tag] += 1
            except ET.ParseError:
                print("Invalid XML:", path)


# Save one row per unique work
with open("greek_english_texts.csv", "w", newline="",
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

print("\nSaved:")
print("  greek_english_texts.csv")
print("  tei_tag_frequencies.csv")
