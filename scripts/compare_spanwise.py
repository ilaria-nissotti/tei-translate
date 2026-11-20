"""How much translation quality does span-wise translation cost?

The pipeline translates every text piece where it is, so an element in the
middle of a sentence (a <pb/>, a <name>, a <note>, ...) cuts the sentence into
pieces that the model translates separately. This script translates the same
Perseus passages (leaf textpart <div>s, as in compare_engines.py) three ways
with one engine and scores each against the Perseus English (chrF / BLEU, tags
and notes removed):

- whole:    the passage's plain text, as one segment (what compare_engines.py does).
            This is the upper bound an aligner could reach.
- split:    cut where the pipeline cuts, but every piece is translated (names
            and numbers too). Difference to `whole` = cost of fragmentation alone.
- pipeline: the real span-wise pipeline with config/policy.yaml (names
            transliterated, <num>/<bibl>/<foreign> kept, ...).
- hybrid:   the hybrid pipeline (tags removed, sentences translated whole, tags
            placed back with the word aligner --aligner); blocks it cannot place
            go span-wise, as in the real pipeline.

A passage is "split" when at least one of its blocks reaches the model in more
than one piece. By default only split passages are sampled (that is where the
cost is); --reuse takes the passages of an earlier compare_engines.py run (a
random sample) and reuses its `whole` translations for the engine.

    python scripts/compare_spanwise.py --engine opus-grk-en --per-work 4
    python scripts/compare_spanwise.py --engine madlad-3b --reuse outputs/compare/20261119-madlad
    python scripts/compare_spanwise.py --engine pivot-grc-el-en --reuse outputs/spanwise/20261120-madlad-split --every 2

--reuse also takes an earlier outputs/spanwise/<run>/ folder (same passages); --every K keeps
every K-th passage of the selection (e.g. half of it, spread over the works).

Writes outputs/spanwise/<timestamp>/report.md, translations.jsonl and run.json.
Needs data/perseus/ (scripts/data/build_dataset.py) and pip install -e .[mt].
"""

from __future__ import annotations

import argparse
import copy
import csv
import dataclasses
import json
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from lxml import etree

# Sibling script: passage selection and plain-text extraction are shared.
from compare_engines import PERSEUS, REPO_ROOT, SKIP, WORKS, plain_text, units

from tei_translate.align import get_aligner
from tei_translate.engines import get_engine
from tei_translate.metrics.translation_scores import bleu, chrf
from tei_translate.pipeline.document import Report, apply_spans
from tei_translate.pipeline.hybrid import run_hybrid
from tei_translate.pipeline.policy import Policy, local_name
from tei_translate.pipeline.spans import WalkReport, collect_spans, has_letters

CONDITIONS = ("whole", "split", "pipeline", "hybrid")
log = logging.getLogger("tei_translate")


def leaf_divs(path: Path) -> dict:
    """Citation ref -> leaf textpart <div> element (same refs as compare_engines.units)."""
    tree = etree.parse(str(path))
    out = {}
    for div in tree.xpath("//*[local-name()='text']//*[local-name()='div'][@type='textpart']"
                          "[not(.//*[local-name()='div'][@type='textpart'])]"):
        chain = [a.get("n") for a in div.iterancestors()
                 if etree.QName(a).localname == "div" and a.get("type") == "textpart"][::-1]
        out[".".join(str(n) for n in chain + [div.get("n")])] = div
    return out


def flat(text: str) -> str:
    return " ".join(text.split())


def translate_all(policy: Policy) -> Policy:
    """The same policy, but keep/transliterate spans are translated: same cuts, no special treatment."""
    def swap(rule):
        if rule.treatment in ("keep", "transliterate") and rule.role in ("inline", "block"):
            return dataclasses.replace(rule, treatment="translate")
        return rule
    p = copy.copy(policy)
    p.default = swap(policy.default)
    p.tags = {name: swap(r) for name, r in policy.tags.items()}
    p.overrides = [(t, a, swap(r)) for t, a, r in policy.overrides]
    return p


def block_of(span, policy: Policy):
    e = span.elem if span.slot == "text" else span.elem.getparent()
    while e is not None and policy.classify(e).role != "block":
        e = e.getparent()
    return e


def fragmentation(div, policy: Policy) -> dict:
    """Pieces sent to the model vs blocks, and which elements cut a block.

    Blocks inside SKIP elements (e.g. a <head>) are ignored: their text is not scored.
    """
    spans, _ = collect_spans(div, policy)
    spans = [s for s in spans if has_letters(s.value)]
    blocks = {}
    for s in spans:
        b = block_of(s, policy)
        if b is None or any(local_name(a) in SKIP for a in (b, *b.iterancestors())):
            continue
        blocks.setdefault(id(b), (b, []))[1].append(s)
    cutters = set()
    for b, ss in blocks.values():
        if len(ss) > 1:
            cutters |= {local_name(c) for c in b.iterdescendants() if isinstance(c.tag, str)}
    return {"pieces": len(spans), "blocks": len(blocks),
            "split_blocks": sum(len(ss) > 1 for _, ss in blocks.values()), "cutters": sorted(cutters)}


def load_greek_english(work_id: str):
    with open(PERSEUS / "pairs.csv", encoding="utf-8") as f:
        pairs = [r for r in csv.DictReader(f) if r["work_id"] == work_id]
    if not pairs:
        return None, None
    return leaf_divs(PERSEUS / pairs[0]["greek_path"]), [units(PERSEUS / r["english_path"]) for r in pairs]


def sample_split(per_work: int, seed: int, min_words: int, policy: Policy) -> list[dict]:
    rng = random.Random(seed)
    cut_policy = translate_all(policy)
    samples = []
    for work_id, label, max_words in WORKS:
        greek, english = load_greek_english(work_id)
        if greek is None:
            log.warning("%s not in data/perseus/pairs.csv, skipped", work_id)
            continue
        candidates = []
        for ref, div in sorted(greek.items()):
            n = len(plain_text(div).split())
            if min_words <= n <= max_words and any(e.get(ref) for e in english):
                frag = fragmentation(div, cut_policy)
                if frag["split_blocks"]:
                    candidates.append(ref)
        log.info("%s: %d split passages of %d-%d words", work_id, len(candidates), min_words, max_words)
        for ref in rng.sample(candidates, min(per_work, len(candidates))):
            samples.append({"work": work_id, "label": label, "ref": ref, "div": greek[ref],
                            "references": [e[ref] for e in english if e.get(ref)]})
    return samples


def load_reused(run_dir: Path, engine_name: str) -> tuple[list[dict], list[str] | None]:
    with open(run_dir / "translations.jsonl", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    labels = {w: l for w, l, _ in WORKS}
    samples, divs = [], {}
    for r in rows:
        if r["work"] not in divs:
            divs[r["work"]] = load_greek_english(r["work"])[0]
        div = divs[r["work"]][r["ref"]]
        if flat(plain_text(div)) != r["greek"]:
            raise ValueError(f"{r['work']} {r['ref']}: Greek text differs from {run_dir}")
        samples.append({"work": r["work"], "label": labels.get(r["work"], r.get("label", "")),
                        "ref": r["ref"], "div": div, "references": r["references"]})
    whole = [r[engine_name] for r in rows] if engine_name in rows[0] else None
    return samples, whole


def run_spanwise(samples, policy: Policy, engine) -> tuple[list[str], Report]:
    """Span-wise translation of every passage, one batch for all; returns plain-text outputs."""
    copies = [copy.deepcopy(s["div"]) for s in samples]
    spans = []
    walk = WalkReport()
    for div in copies:
        s, w = collect_spans(div, policy)
        spans += s
        walk.cases.update(w.cases)
    report = Report(engine.name, "grc", "en", walk)
    apply_spans(spans, engine, "grc", "en", report)
    return [flat(plain_text(div)) for div in copies], report


def run_hybrid_passages(samples, policy: Policy, engine, aligner) -> tuple[list[str], Report]:
    """Hybrid translation of every passage (one engine batch, one aligner batch, then the
    span-wise batch for what is left); returns plain-text outputs."""
    copies = [copy.deepcopy(s["div"]) for s in samples]
    spans = []
    walk = WalkReport()
    for div in copies:
        s, w = collect_spans(div, policy)
        spans += s
        walk.cases.update(w.cases)
    report = Report(engine.name, "grc", "en", walk, placement="hybrid", aligner=aligner.name)
    rest = run_hybrid(spans, policy, engine, aligner, "grc", "en", report.hybrid)
    apply_spans(rest, engine, "grc", "en", report)
    return [flat(plain_text(div)) for div in copies], report


def score(samples, hyps, idx=None):
    idx = range(len(samples)) if idx is None else idx
    refs = [samples[i]["references"] for i in idx]
    h = [hyps[i] for i in idx]
    return (chrf(refs, h), bleu(refs, h)) if h else (float("nan"), float("nan"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--engine", default="opus-grk-en")
    parser.add_argument("--per-work", type=int, default=6, help="split passages per work (default 6)")
    parser.add_argument("--min-words", type=int, default=15)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--reuse", type=Path, metavar="RUN_DIR",
                        help="an outputs/compare/<run>/ folder: use its passages (and its `whole` "
                             "translations if it has this engine) instead of sampling split passages")
    parser.add_argument("--every", type=int, default=1, metavar="K",
                        help="keep every K-th passage of the selection (default 1: all)")
    parser.add_argument("--aligner", default="ugarit", help="word aligner for the hybrid condition")
    parser.add_argument("--out", type=Path, help="default: outputs/spanwise/<timestamp>/")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    log.setLevel(logging.INFO)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    policy = Policy.load()
    cut_policy = translate_all(policy)
    whole = None
    if args.reuse:
        samples, whole = load_reused(args.reuse, args.engine)
        selection = f"the {len(samples)} passages of {args.reuse.as_posix()}"
    else:
        samples = sample_split(args.per_work, args.seed, args.min_words, policy)
        selection = (f"{len(samples)} split passages, up to {args.per_work} per work "
                     f"(seed {args.seed}, at least {args.min_words} words)")
    if args.every > 1:
        keep = list(range(0, len(samples), args.every))
        samples = [samples[i] for i in keep]
        whole = [whole[i] for i in keep] if whole is not None else None
        selection += f", every {args.every}. passage kept ({len(samples)})"
    for s in samples:
        s["greek"] = flat(plain_text(s["div"]))
        s.update(fragmentation(s["div"], cut_policy))
    words = sum(len(s["greek"].split()) for s in samples)
    log.info("%d passages, %d Greek words, %d split", len(samples), words,
             sum(bool(s["split_blocks"]) for s in samples))

    engine = get_engine(args.engine)
    engine.translate(["λόγος."], "grc", "en")  # load the model outside the timing
    hyps, seconds, reports = {}, {}, {}
    if whole is not None:
        hyps["whole"], seconds["whole"] = whole, None
        log.info("whole: reusing translations from %s", args.reuse)
    else:
        start = time.perf_counter()
        hyps["whole"] = engine.translate([s["greek"] for s in samples], "grc", "en")
        seconds["whole"] = time.perf_counter() - start
    for name, pol in (("split", cut_policy), ("pipeline", policy)):
        log.info("%s: translating", name)
        start = time.perf_counter()
        hyps[name], reports[name] = run_spanwise(samples, pol, engine)
        seconds[name] = time.perf_counter() - start
    aligner = get_aligner(args.aligner)
    aligner.align([(["λόγος"], ["word"])])  # load the aligner outside the timing
    log.info("hybrid: translating")
    start = time.perf_counter()
    hyps["hybrid"], reports["hybrid"] = run_hybrid_passages(samples, policy, engine, aligner)
    seconds["hybrid"] = time.perf_counter() - start
    h = reports["hybrid"].hybrid

    out = args.out or REPO_ROOT / "outputs" / "spanwise" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    keys = ("work", "label", "ref", "greek", "references", "pieces", "blocks", "split_blocks", "cutters")
    with open(out / "translations.jsonl", "w", encoding="utf-8") as f:
        for i, s in enumerate(samples):
            row = {k: s[k] for k in keys} | {c: hyps[c][i] for c in CONDITIONS}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    run = {"engine": args.engine, "model": engine.name, "selection": selection, "seed": args.seed,
           "seconds": seconds,
           "segments": {c: reports[c].translated_spans for c in reports},
           "transliterated": {c: reports[c].transliterated_spans for c in reports},
           "hybrid": {"aligner": aligner.name, "blocks_placed": h.blocks, "sentences": h.sentences,
                      "aligned_sentences": h.aligned_sentences, "spanwise_blocks": dict(h.spanwise),
                      "placements": dict(h.placements)}}
    (out / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")

    split_idx = [i for i, s in enumerate(samples) if s["split_blocks"]]
    blocks = sum(s["blocks"] for s in samples)
    lines = [f"# Span-wise vs whole-passage translation ({datetime.now():%Y-%m-%d})", "",
             f"Engine `{args.engine}` (`{engine.name}`). {selection}; {words} Greek words. "
             f"{len(split_idx)} of {len(samples)} passages have a block cut into pieces; "
             f"{reports['split'].translated_spans} pieces sent in `split` for {blocks} blocks. "
             "Corpus chrF / BLEU against the Perseus English, notes/bibl/head removed. "
             f"hybrid (aligner `{aligner.name}`): {h.blocks} blocks placed, "
             f"{sum(h.spanwise.values())} span-wise ({', '.join(f'{k} {v}' for k, v in h.spanwise.most_common()) or '-'}); "
             f"tags placed: {', '.join(f'{k} {v}' for k, v in sorted(h.placements.items())) or '-'}.", "",
             "| Condition | chrF (all) | BLEU (all) | chrF (split passages) | BLEU (split passages) | Time (s) |",
             "|---|---|---|---|---|---|"]
    for c in CONDITIONS:
        ca, ba = score(samples, hyps[c])
        cs, bs = score(samples, hyps[c], split_idx)
        secs = "reused" if seconds[c] is None else f"{seconds[c]:.0f}"
        lines.append(f"| {c} | {ca:.1f} | {ba:.1f} | {cs:.1f} | {bs:.1f} | {secs} |")
    lines += ["", "## chrF per work (all passages)", "",
              "| Work | n | split passages | " + " | ".join(CONDITIONS) + " |",
              "|---|---|---|" + "---|" * len(CONDITIONS)]
    for work_id, label, _ in WORKS:
        idx = [i for i, s in enumerate(samples) if s["work"] == work_id]
        if idx:
            cells = [f"{score(samples, hyps[c], idx)[0]:.1f}" for c in CONDITIONS]
            n_split = sum(bool(samples[i]["split_blocks"]) for i in idx)
            lines.append(f"| {label} | {len(idx)} | {n_split} | " + " | ".join(cells) + " |")

    gains = sorted(split_idx, key=lambda i: score(samples, hyps["pipeline"], [i])[0]
                   - score(samples, hyps["hybrid"], [i])[0])
    lines += ["", "## Largest differences (pipeline → hybrid, passage chrF)", ""]
    for i in gains[:3] + gains[-2:]:
        s = samples[i]
        d = {c: score(samples, hyps[c], [i])[0] for c in CONDITIONS}
        lines += [f"### {s['label']}, {s['ref']} (cut by: {', '.join(s['cutters'])})", "",
                  ", ".join(f"chrF {c} {d[c]:.1f}" for c in CONDITIONS), "",
                  f"- **Greek:** {s['greek']}", f"- **Reference:** {s['references'][0]}"]
        lines += [f"- **{c}:** {hyps[c][i]}" for c in CONDITIONS] + [""]
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:6 + len(CONDITIONS)]))
    print(f"\nwritten: {out / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
