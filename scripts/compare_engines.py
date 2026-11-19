"""Compare MT engines on Perseus Greek passages that have an English translation.

Plain-text MT quality only (no XML): each sample is one citation unit (e.g. a
section of Herodotus) taken from the Greek file, and its English reference is
the unit with the same citation in the English file(s) of the same work. Notes
are removed on both sides. Scores are corpus-level chrF and BLEU
(tei_translate.metrics.translation_scores), overall and per work.

Needs data/perseus/ (python scripts/data/build_dataset.py) and, for model
engines, pip install -e .[mt].

    python scripts/compare_engines.py                       # opus-grk-en vs opus-bible-ine
    python scripts/compare_engines.py --engines opus-grk-en madlad-3b --per-work 4

Writes outputs/compare/<timestamp>/report.md and translations.jsonl.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from lxml import etree

from tei_translate.engines import get_engine
from tei_translate.metrics.translation_scores import bleu, chrf

REPO_ROOT = Path(__file__).resolve().parents[1]
PERSEUS = REPO_ROOT / "data" / "perseus"

# (work id, label, max Greek words per sample). Prose is cited by section, so
# samples are short; Pindar's odes are the smallest unit shared with the English.
WORKS = [
    ("tlg0016.tlg001", "Herodotus, Histories (Ionic prose)", 120),
    ("tlg0003.tlg001", "Thucydides, History (Attic prose)", 120),
    ("tlg0032.tlg006", "Xenophon, Anabasis (Attic prose)", 120),
    ("tlg0007.tlg012", "Plutarch, Pericles (imperial prose)", 120),
    ("tlg0526.tlg001", "Josephus, Jewish Antiquities (1st c. CE prose)", 120),
    ("tlg0525.tlg001", "Pausanias, Description of Greece (2nd c. CE prose)", 120),
    ("tlg0033.tlg001", "Pindar, Olympian Odes (lyric poetry, whole odes)", 400),
]
# Not part of the running text. <reg> holds gazetteer forms in some English files
# ("+Vardar [22.833,40.583] (river), Europe"), next to the translator's own word.
SKIP = {"note", "bibl", "head", "reg"}


def units(path: Path) -> dict[str, str]:
    """Citation ref (e.g. '1.2.3') -> plain text, for every leaf textpart <div>."""
    tree = etree.parse(str(path))
    out = {}
    for div in tree.xpath("//*[local-name()='text']//*[local-name()='div'][@type='textpart']"
                          "[not(.//*[local-name()='div'][@type='textpart'])]"):
        chain = [a.get("n") for a in div.iterancestors()
                 if etree.QName(a).localname == "div" and a.get("type") == "textpart"][::-1]
        ref = ".".join(str(n) for n in chain + [div.get("n")])
        out[ref] = " ".join(plain_text(div).split())
    return out


def plain_text(elem) -> str:
    parts = []

    def visit(e):
        if isinstance(e.tag, str) and etree.QName(e).localname in SKIP:
            return
        if e.text and isinstance(e.tag, str):
            parts.append(e.text)
        for child in e:
            visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(elem)
    return " ".join(parts)


def load_samples(per_work: int, seed: int, min_words: int) -> list[dict]:
    with open(PERSEUS / "pairs.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rng = random.Random(seed)
    samples = []
    for work_id, label, max_words in WORKS:
        pairs = [r for r in rows if r["work_id"] == work_id]
        if not pairs:
            logging.warning("%s not in data/perseus/pairs.csv, skipped", work_id)
            continue
        greek = units(PERSEUS / pairs[0]["greek_path"])
        english = [units(PERSEUS / r["english_path"]) for r in pairs]
        candidates = sorted(
            ref for ref, text in greek.items()
            if min_words <= len(text.split()) <= max_words and any(e.get(ref) for e in english))
        if not candidates:
            logging.warning("%s: no aligned units of %d-%d words", work_id, min_words, max_words)
            continue
        for ref in rng.sample(candidates, min(per_work, len(candidates))):
            samples.append({"work": work_id, "label": label, "ref": ref, "greek": greek[ref],
                            "references": [e[ref] for e in english if e.get(ref)]})
    return samples


def score(samples, hyps):
    refs = [s["references"] for s in samples]
    return chrf(refs, hyps), bleu(refs, hyps)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--engines", nargs="+", default=["opus-grk-en", "opus-bible-ine"])
    parser.add_argument("--per-work", type=int, default=8, help="samples per work (default 8)")
    parser.add_argument("--min-words", type=int, default=15)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, help="default: outputs/compare/<timestamp>/")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    logging.getLogger("tei_translate").setLevel(logging.INFO)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    samples = load_samples(args.per_work, args.seed, args.min_words)
    words = sum(len(s["greek"].split()) for s in samples)
    logging.getLogger("tei_translate").info("%d samples, %d Greek words", len(samples), words)

    results = {}
    for name in args.engines:
        engine = get_engine(name)
        engine.translate(["λόγος."], "grc", "en")  # load the model outside the timing
        start = time.perf_counter()
        hyps = engine.translate([s["greek"] for s in samples], "grc", "en")
        results[name] = {"model": engine.name, "hyps": hyps, "seconds": time.perf_counter() - start}

    out = args.out or REPO_ROOT / "outputs" / "compare" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "translations.jsonl", "w", encoding="utf-8") as f:
        for i, s in enumerate(samples):
            row = dict(s, **{name: r["hyps"][i] for name, r in results.items()})
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    lines = [f"# Engine comparison ({datetime.now():%Y-%m-%d})", "",
             f"{len(samples)} Perseus passages ({words} Greek words), seed {args.seed}, "
             f"up to {args.per_work} per work. Corpus-level chrF / BLEU against the Perseus English "
             "(several references where the work has several translations). Notes removed.", "",
             "| Engine | Model | chrF | BLEU | Time (s) |", "|---|---|---|---|---|"]
    for name, r in results.items():
        c, b = score(samples, r["hyps"])
        lines.append(f"| {name} | `{r['model']}` | {c:.1f} | {b:.1f} | {r['seconds']:.0f} |")
    lines += ["", "## chrF per work", "",
              "| Work | n | " + " | ".join(results) + " |", "|---|---|" + "---|" * len(results)]
    for work_id, label, _ in WORKS:
        idx = [i for i, s in enumerate(samples) if s["work"] == work_id]
        if not idx:
            continue
        sub = [samples[i] for i in idx]
        cells = [f"{score(sub, [r['hyps'][i] for i in idx])[0]:.1f}" for r in results.values()]
        lines.append(f"| {label} | {len(idx)} | " + " | ".join(cells) + " |")
    lines += ["", "## Examples (first sample of each work)", ""]
    for work_id, label, _ in WORKS:
        i = next((i for i, s in enumerate(samples) if s["work"] == work_id), None)
        if i is None:
            continue
        s = samples[i]
        lines += [f"### {label}, {s['ref']}", "", f"- **Greek:** {s['greek']}",
                  f"- **Reference:** {s['references'][0]}"]
        lines += [f"- **{name}:** {r['hyps'][i]}" for name, r in results.items()]
        lines.append("")
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:8 + len(results)]))
    print(f"\nwritten: {out / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
