"""Time one engine with a limited number of CPU threads (to mimic the free HF Space: 2 vCPU).

Reuses the passages of an earlier compare_engines.py run (RUN_DIR/translations.jsonl),
keeps every K-th one, and prints one JSON line: load time, translation time, words/s,
how many outputs equal the stored ones, peak memory (Windows only) and, with
--aligner, the aligner's load time and seconds per sentence pair. Run one engine
per process so the memory peaks don't mix. Needs pip install -e .[mt].

    python scripts/bench_engine_threads.py madlad-3b 2 outputs/compare/20261119-madlad --every 5 --aligner ugarit
    python scripts/bench_engine_threads.py madlad-3b 2 outputs/compare/20261119-madlad --every 54 --aligner ugarit  # memory only
"""
import argparse, ctypes, json, os, sys, time

ap = argparse.ArgumentParser()
ap.add_argument("engine")
ap.add_argument("threads", type=int)
ap.add_argument("run_dir")
ap.add_argument("--every", type=int, default=5)
ap.add_argument("--aligner")
ap.add_argument("--out")
args = ap.parse_args()

for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[var] = str(args.threads)
import torch  # noqa: E402
torch.set_num_threads(args.threads)
torch.set_num_interop_threads(1)


def peak_mb():
    class PMC(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    c = PMC(); c.cb = ctypes.sizeof(c)
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
        raise ctypes.WinError()
    return {"peak_working_set_mb": round(c.PeakWorkingSetSize / 2**20),
            "peak_committed_mb": round(c.PeakPagefileUsage / 2**20)}


from tei_translate.engines import get_engine  # noqa: E402

rows = [json.loads(l) for l in open(os.path.join(args.run_dir, "translations.jsonl"), encoding="utf-8")]
rows = rows[::args.every]
greek = [r["greek"] for r in rows]
words = sum(len(g.split()) for g in greek)

engine = get_engine(args.engine)
t0 = time.perf_counter()
engine.translate(["Καλημέρα."], "grc", "en")   # forces the model load (+ one tiny sentence)
load_s = time.perf_counter() - t0
t0 = time.perf_counter()
out = engine.translate(greek, "grc", "en")
mt_s = time.perf_counter() - t0
result = {"engine": args.engine, "threads": torch.get_num_threads(), "passages": len(greek), "words": words,
          "load_s": round(load_s, 1), "translate_s": round(mt_s, 1), "words_per_s": round(words / mt_s, 2),
          "same_as_stored": sum(o == r.get(args.engine) for o, r in zip(out, rows)), **peak_mb()}

if args.aligner:
    from tei_translate.align import get_aligner
    from tei_translate.pipeline.sentences import split_sentences
    from tei_translate.align.base import word_spans
    words_of = lambda t: [t[a:b] for a, b in word_spans(t)]
    aligner = get_aligner(args.aligner)
    pairs = []
    for g, e in zip(greek, out):
        gs = [g[a:b] for a, b in split_sentences(g)]
        es = [e[a:b] for a, b in split_sentences(e)]
        # timing only: sentences paired by position (the pipeline pairs each Greek sentence with its own translation)
        pairs += [(words_of(a), words_of(b)) for a, b in zip(gs, es)]
    t0 = time.perf_counter()
    aligner.align(pairs[:1])
    result["aligner_load_s"] = round(time.perf_counter() - t0, 1)
    t0 = time.perf_counter()
    aligner.align(pairs)
    result["aligner_pairs"] = len(pairs)
    result["aligner_s_per_pair"] = round((time.perf_counter() - t0) / max(len(pairs), 1), 2)
    result.update({k + "_with_aligner": v for k, v in peak_mb().items()})

print(json.dumps(result))
if args.out:
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"result": result, "outputs": out}, f, ensure_ascii=False, indent=1)
