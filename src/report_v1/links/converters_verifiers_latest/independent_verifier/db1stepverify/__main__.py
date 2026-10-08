"""CLI.
  python -m db1stepverify sample  --out RUN [--n 40] [--results-dir DIR] [--census FILE] [--max-step-mb 150]
  python -m db1stepverify run     --out RUN [--work DIR] [--vlm queue|api|none] [--no-repro] [--listing-dir DIR] [--workers 2]
  python -m db1stepverify one SHA --out RUN ...
  python -m db1stepverify reverdict --out RUN       (after VLM answers arrive)
  python -m db1stepverify report  --out RUN [--suffix _v2]
  python -m db1stepverify inputs  --out RUN [--results-dir DIR] [--listing-dir DIR]   (every published STEP: is its input there?)"""
import argparse, json, os, sys, glob, concurrent.futures as cf
from . import config as C


def main():
    ap = argparse.ArgumentParser(prog="db1stepverify")
    ap.add_argument("cmd", choices=["sample", "prep", "run", "one", "reverdict", "report", "inputs", "fleet", "html"])
    ap.add_argument("--hours", type=float, default=12, help="prep: presigned URL lifetime")
    ap.add_argument("sha", nargs="?")
    ap.add_argument("--out", required=True)
    ap.add_argument("--work", default=None)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--results-dir"); ap.add_argument("--census"); ap.add_argument("--listing-dir")
    ap.add_argument("--max-step-mb", type=float, default=150)
    ap.add_argument("--force", default="", help="comma-separated shas always included in the sample")
    ap.add_argument("--vlm", default="queue", choices=["queue", "api", "none"])
    ap.add_argument("--no-repro", action="store_true"); ap.add_argument("--no-truth", action="store_true")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--suffix", default="")
    ap.add_argument("--shard", default="", help="i/n")
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--delete-files", action="store_true", help="remove downloaded STEP/db1 after each file")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    work = a.work or os.path.join(a.out, "_work")

    if a.cmd == "sample":
        from .sample import load_records, load_census, choose
        R = load_records(a.results_dir); cen = load_census(a.census)
        from . import s3io
        sizes = {}
        pg = s3io.s3().get_paginator("list_objects_v2")
        for page in pg.paginate(Bucket=C.BUCKET, Prefix=C.STEP_PREFIX):
            for o in page.get("Contents", []): sizes[os.path.basename(o["Key"])[:-4]] = o["Size"]
        S = choose(R, cen, a.n, a.max_step_mb * 1e6, step_sizes=sizes, force=[x for x in a.force.split(",") if x])
        json.dump(dict(n=len(S), seed=C.SEED, published=len(sizes), records=len(R), sample=S), open(os.path.join(a.out, "sample.json"), "w"), indent=1)
        for s in S: print(s["sha"][:16], s["engine"], round(s["step_bytes"] / 1e6, 1), "MB", s["reason"], s["flags"])
        print(len(S), "picked ->", os.path.join(a.out, "sample.json"))
    elif a.cmd in ("run", "one"):
        from .verify import verify
        shas = [a.sha] if a.cmd == "one" else [s["sha"] for s in json.load(open(os.path.join(a.out, "sample.json")))["sample"]]
        done = {os.path.basename(f)[:16] for f in glob.glob(os.path.join(a.out, "*.json"))}
        todo = [s for s in shas if s[:16] not in done or a.cmd == "one"]
        if a.shard:                                    # i/n: this process takes every n-th file (run n processes, no GIL sharing)
            i, n = map(int, a.shard.split("/")); todo = todo[i::n]
        print(f"{len(todo)} to verify ({len(shas) - len(todo)} already done)", flush=True)

        def one(s):
            r, run = verify(s, work, a.out, a.listing_dir, not a.no_repro, not a.no_truth, a.vlm, keep_files=not a.delete_files,
                            log=lambda m: print(m, flush=True))
            print(f"{s[:16]} {r['verdict']:5s} evidence={r['evidence']} {' '.join(c for c in r['codes'] if not c.startswith('I_'))} "
                  f"({run['t_total_s']}s)", flush=True)
        if a.workers > 1:
            with cf.ThreadPoolExecutor(a.workers) as ex: list(ex.map(one, todo))
        else:
            for s in todo: one(s)
        if not a.no_report:
            from .report import write
            print(write(a.out, a.suffix))
    elif a.cmd == "prep":
        # everything a machine WITHOUT S3 rights needs for the sample: records, heads, sibling lists, presigned URLs
        from . import s3io
        from .reproduce import SRC_FILES
        S = json.load(open(os.path.join(a.out, "sample.json")))["sample"]
        M = dict(records={}, heads={}, urls={}, source={}, siblings={}, hours=a.hours)
        def put(bucket, key):
            M["heads"][f"{bucket}/{key}"] = s3io.head(bucket, key)
            if "error" not in M["heads"][f"{bucket}/{key}"]: M["urls"][f"{bucket}/{key}"] = s3io.presign(bucket, key, a.hours)
        for f in SRC_FILES: put(C.BUCKET, f"{C.CTL_PREFIX}src/{f}")
        for f in ("tekla_profiles.json", "layouts.json"): put(C.BUCKET, f"{C.CTL_PREFIX}{f}")
        def one_prep(s):
            sha = s["sha"]; rec = s3io.record(sha); key = rec.get("key")
            out = dict(sha=sha, rec=rec, key=key, heads=[], sib=[], src=None)
            out["heads"].append((C.BUCKET, f"{C.STEP_PREFIX}{sha}.stp"))
            if key:
                out["heads"].append((C.BUCKET, key)); out["src"] = s3io.locate_in_source_bucket(key, a.listing_dir)
                out["sib"] = s3io.sibling_ifcs(key)
                for c in [c for c in out["sib"] if c["tekla"] and not c["grid_export"]][:2]: out["heads"].append((C.BUCKET, c["key"]))
            return out
        with cf.ThreadPoolExecutor(16) as ex:
            for o in ex.map(one_prep, S):
                M["records"][o["sha"]] = o["rec"]
                if o["key"]: M["source"][o["key"]] = o["src"]; M["siblings"][o["key"]] = o["sib"]
                for b, k in o["heads"]: put(b, k)
        p = os.path.join(a.out, "offline_manifest.json"); json.dump(M, open(p, "w"), default=str)
        print(f"manifest: {len(M['records'])} records, {len(M['urls'])} presigned URLs ({a.hours} h) -> {p}")
    elif a.cmd == "fleet":
        from .sample import load_records
        from . import fleet, s3io
        R = load_records(a.results_dir); sizes = {}
        for page in s3io.s3().get_paginator("list_objects_v2").paginate(Bucket=C.BUCKET, Prefix=C.STEP_PREFIX):
            for o in page.get("Contents", []): sizes[os.path.basename(o["Key"])[:-4]] = o["Size"]
        ip = os.path.join(a.out, "inputs.jsonl")
        inputs = {json.loads(l)["sha"]: json.loads(l) for l in open(ip)} if os.path.exists(ip) else None
        s, f = fleet.run(R, sizes, inputs); fleet.write(a.out, s, f, a.suffix)
        print(json.dumps(s, indent=1))
    elif a.cmd == "reverdict":
        from .verify import reverdict
        for f in sorted(glob.glob(os.path.join(a.out, "*.json"))):
            b = os.path.basename(f)
            import re
            if re.fullmatch(r"[0-9a-f]{16}\.json", b):
                r = reverdict(f); print(b[:16], r["verdict"], " ".join(c for c in r["codes"] if not c.startswith("I_")))
        from .report import write
        print(write(a.out, a.suffix))
    elif a.cmd == "report":
        from .report import write
        print(write(a.out, a.suffix))
    elif a.cmd == "html":
        from .htmlreport import build
        print(build(a.out, a.suffix))
    elif a.cmd == "inputs":
        from .sample import load_records
        from . import s3io
        R = {k: r for k, r in load_records(a.results_dir).items() if r.get("status") == "ok"}
        if a.listing_dir: s3io._src_index(a.listing_dir)       # build the source-bucket index once, before the threads
        def chk(k):
            h = s3io.head(C.BUCKET, R[k]["key"]); d = dict(sha=k, key=R[k]["key"], in_bucket="error" not in h, bytes_ok=h.get("bytes") == R[k].get("db1_bytes"))
            if not d["in_bucket"] or a.listing_dir: d["source_bucket"] = s3io.locate_in_source_bucket(R[k]["key"], a.listing_dir)
            return d
        with cf.ThreadPoolExecutor(48) as ex: rows = list(ex.map(chk, sorted(R)))
        with open(os.path.join(a.out, f"inputs{a.suffix}.jsonl"), "w") as f:
            for r in rows: f.write(json.dumps(r) + "\n")
        miss = [r for r in rows if not r["in_bucket"]]
        print(f"published STEP: {len(rows)}; input present: {len(rows) - len(miss)}; size ok: {sum(r['bytes_ok'] for r in rows)}; "
              f"missing: {len(miss)} (found in {C.SRC_BUCKET}: {sum(1 for r in miss if r.get('source_bucket', {}).get('found'))})")
        if a.listing_dir:
            import collections
            print("source archive located:", collections.Counter(r["source_bucket"]["how"] for r in rows))


if __name__ == "__main__":
    main()
