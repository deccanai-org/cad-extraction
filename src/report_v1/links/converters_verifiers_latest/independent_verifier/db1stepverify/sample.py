"""Stratified, deterministic sample of published conversions: every Xsteel engine represented, weighted by volume,
at least half with a Tekla export next to the .db1 (ground truth), plus every risk flag the records show."""
import json, os, glob, collections, random
from . import config as C


def load_records(results_dir=None):
    """all production result records; from a local mirror (aws s3 sync) or straight from S3"""
    if results_dir:
        return {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob(os.path.join(results_dir, "*.json"))}
    from . import s3io
    import concurrent.futures as cf
    keys = []
    for page in s3io.s3().get_paginator("list_objects_v2").paginate(Bucket=C.BUCKET, Prefix=C.RESULTS_PREFIX):
        keys += [o["Key"] for o in page.get("Contents", [])]
    with cf.ThreadPoolExecutor(32) as ex:
        vals = list(ex.map(lambda k: s3io.get_json(C.BUCKET, k), keys))
    return {os.path.basename(k)[:-5]: v for k, v in zip(keys, vals)}


def load_census(path=None):
    """sibling-IFC counts per input sha (census of the old converter's non-OK files = this job pool)"""
    if path and os.path.exists(path):
        rows = [json.loads(l) for l in open(path)]
    else:
        from . import s3io
        rows = [json.loads(l) for l in s3io.s3().get_object(Bucket=C.BUCKET, Key=f"{C.CTL_PREFIX}census.jsonl")["Body"].read().decode().splitlines() if l]
    return {r["sha"]: r for r in rows}


def flags(r):
    c = r.get("convert") or {}; f = []
    sk = c.get("skipped") or {}
    lost = sum(sk.get(k, 0) for k in ("unresolved", "contour_plate_no_outline", "implausible_profile"))
    if (c.get("written") or 0) and lost / (lost + c["written"]) > 0.3: f.append("decoder_loss")
    yv = c.get("y_vertical_frac_I")
    if yv is not None and (c.get("horizontal_I") or 0) >= 20 and yv < 0.8: f.append("orientation")
    if r.get("excluded_elements"): f.append("rescue")
    sp = (r.get("step_stats") or {}).get("parts")
    if sp is not None and c.get("written") is not None and sp != c["written"]: f.append("parts_dropped")
    if (r.get("readback") or {}).get("read_status") == "ok" and (r["readback"].get("solids") or 0) < (sp or 0): f.append("readback_short")
    return f


def choose(records, census, n=40, max_step_bytes=150e6, seed=C.SEED, step_sizes=None, force=()):
    ok = {k: r for k, r in records.items() if r.get("status") == "ok"}
    sz = lambda k: (step_sizes or {}).get(k) or ok[k].get("out_bytes") or 0
    pool = [k for k in sorted(ok) if 20_000 < sz(k) <= max_step_bytes]
    rng = random.Random(seed)
    by_eng = collections.defaultdict(list)
    for k in pool: by_eng[ok[k].get("engine")].append(k)
    total = sum(len(v) for v in by_eng.values())
    picked = []; why = {}

    def take(k, reason):
        if k not in why: picked.append(k); why[k] = reason

    for k in force:
        if k in ok: take(k, "forced")
    # 1. risk flags: one per flag, preferring files with a Tekla export
    fl = {k: flags(ok[k]) for k in pool}
    for flag in ("orientation", "rescue", "parts_dropped", "decoder_loss", "readback_short"):
        c = [k for k in pool if flag in fl[k]]
        c.sort(key=lambda k: (-(census.get(k, {}).get("sib_ifc") or 0) > 0, k))
        rng.shuffle(c); c.sort(key=lambda k: not (census.get(k, {}).get("sib_ifc") or 0))
        for k in c[:2 if flag in ("orientation", "parts_dropped") else 1]: take(k, f"flag:{flag}")
    # 2. every engine at least once, then proportional; half of each engine's picks with ground truth
    rest = n - len(picked)
    quota = {e: max(1, round(rest * len(v) / total)) for e, v in by_eng.items()}
    while sum(quota.values()) > rest:
        e = max(quota, key=lambda e: quota[e]); quota[e] -= 1
    for e in sorted(by_eng, key=lambda e: (e is None, e or "")):
        c = by_eng[e][:]; rng.shuffle(c)
        with_t = [k for k in c if (census.get(k, {}).get("sib_ifc") or 0) > 0 and k not in why]
        without = [k for k in c if k not in with_t and k not in why]
        q = quota[e]; qt = min(len(with_t), max(1, (q + 1) // 2)) if with_t else 0
        for k in with_t[:qt]: take(k, f"engine:{e}+truth")
        for k in (without + with_t[qt:])[:q - qt]: take(k, f"engine:{e}")
    return [dict(sha=k, reason=why[k], engine=ok[k].get("engine"), step_bytes=sz(k), db1_bytes=ok[k].get("db1_bytes"),
                 sib_ifc=census.get(k, {}).get("sib_ifc"), flags=fl.get(k, flags(ok[k])), key=ok[k].get("key")) for k in picked]
