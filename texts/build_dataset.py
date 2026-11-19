#!/usr/bin/env python3
"""
Build a Greek-English parallel-text dataset from the Perseus Digital Library
(PerseusDL/canonical-greekLit on GitHub).

Inputs (same folder as this script, or pass --pairs / --texts):
    greek_english_pairs.csv   work_id, author, title, greek_file, english_file
    greek_english_texts.csv   work_id, author, title, ..., greek_files, english_files, ...

Output layout:
    dataset/
      texts/
        tlg0003.tlg001/
          greek/   tlg0003.tlg001.perseus-grc2.xml
          english/ tlg0003.tlg001.1st1K-eng1.xml, ...
        ...
      pairs.csv        one row per (greek, english) pair, with local paths
      work_types.csv   work_id, type   (type is "poetry", "prose" or "drama",
                       decided from the content of the Greek XML files)
      work_type_details.csv   the measurements behind each decision
      failed_downloads.csv   (only if something failed)

Usage:
    python build_dataset.py
    python build_dataset.py --out my_dataset --workers 16
Re-running is safe: files already downloaded are skipped.
"""
import argparse
import csv
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

RAW_BASE = "https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/master/"

# Poetry / prose / drama classification (by file content) lives in
# make_work_types.py -- keep that file in the same folder as this script.
from texts.make_work_types import build_work_types


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------
def download(rel_path: str, dest: Path, retries: int = 4) -> tuple[str, str | None]:
    """Download one file. Returns (rel_path, error or None)."""
    if dest.exists() and dest.stat().st_size > 0:
        return rel_path, None
    url = RAW_BASE + rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "perseus-dataset-builder"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(data)
            tmp.rename(dest)
            return rel_path, None
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            if e.code == 404:
                break  # no point retrying
        except Exception as e:  # network hiccup, timeout, etc.
            err = repr(e)
        time.sleep(1.5 * (attempt + 1))
    return rel_path, err


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=str(here / "greek_english_pairs.csv"))
    ap.add_argument("--texts", default=str(here / "greek_english_texts.csv"))
    ap.add_argument("--out", default=str(here / "dataset"),
                    help="output folder (default: a 'dataset' folder next to this script)")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    out = Path(args.out).resolve()
    print(f"Output folder: {out}")
    texts_dir = out / "texts"
    texts_dir.mkdir(parents=True, exist_ok=True)

    with open(args.pairs, newline="", encoding="utf-8-sig") as f:
        pairs = list(csv.DictReader(f))
    with open(args.texts, newline="", encoding="utf-8-sig") as f:
        works = list(csv.DictReader(f))

    # ---- collect unique files to download --------------------------------
    jobs = {}  # rel_path -> local Path
    local_pairs = []
    for r in pairs:
        wid = r["work_id"]
        g_rel, e_rel = r["greek_file"].strip(), r["english_file"].strip()
        g_local = texts_dir / wid / "greek" / Path(g_rel).name
        e_local = texts_dir / wid / "english" / Path(e_rel).name
        jobs[g_rel] = g_local
        jobs[e_rel] = e_local
        local_pairs.append({
            "work_id": wid,
            "author": r["author"],
            "title": r["title"],
            "type": "",  # filled in after classification
            "greek_path": g_local.relative_to(out).as_posix(),
            "english_path": e_local.relative_to(out).as_posix(),
        })

    # ---- download ---------------------------------------------------------
    print(f"Downloading {len(jobs)} unique files with {args.workers} workers...")
    failed = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(download, rel, dest) for rel, dest in jobs.items()]
        for fut in as_completed(futs):
            rel, err = fut.result()
            done += 1
            if err:
                failed.append((rel, err))
            if done % 50 == 0 or done == len(futs):
                print(f"  {done}/{len(futs)}  (failed so far: {len(failed)})")

    failed_set = {rel for rel, _ in failed}

    # ---- work_types.csv: classify each work from its Greek file content ---
    print("Classifying works as poetry / prose / drama from file content...")
    types = build_work_types(works, out)

    # ---- pairs.csv (only pairs whose both files exist) --------------------
    kept = 0
    with open(out / "pairs.csv", "w", newline="", encoding="utf-8") as f:
        fields = ["work_id", "author", "title", "type", "greek_path", "english_path"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r, lp in zip(pairs, local_pairs):
            if r["greek_file"].strip() in failed_set or r["english_file"].strip() in failed_set:
                continue
            lp["type"] = types.get(lp["work_id"], "unknown")
            w.writerow(lp)
            kept += 1
    print(f"Wrote {out / 'pairs.csv'} ({kept}/{len(pairs)} pairs)")

    if failed:
        with open(out / "failed_downloads.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["file", "error"])
            w.writerows(failed)
        print(f"{len(failed)} downloads failed; see {out / 'failed_downloads.csv'}. "
              "Re-run the script to retry them.")
        sys.exit(1)
    print(f"Done. Everything is in: {out}")


if __name__ == "__main__":
    main()
