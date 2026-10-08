"""Candidate source IFCs: discover, drop byte-identical copies, score each in a worker process, pick the source.

Determinism: candidates are ordered by (size, path); they are scored in fixed-size batches in that order and scoring
only stops *between* batches once a perfect candidate exists, so the chosen source never depends on timing."""
import os, sys, json, hashlib, tempfile, shutil, subprocess, collections
from concurrent.futures import ThreadPoolExecutor
from . import config as C


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(16 << 20), b""): h.update(b)
    return h.hexdigest()


def discover(paths, base=None, manifest_sha=None):
    """paths: IFC files and/or folders. -> unique candidates [{path, rel, bytes, sha256, copies:[rel...]}], sorted."""
    files = []
    for p in paths:
        if os.path.isdir(p):
            for d, _, fs in os.walk(p):
                files += [os.path.join(d, x) for x in fs if x.lower().endswith(".ifc")]
        elif p.lower().endswith(".ifc") and os.path.exists(p):
            files.append(p)
    rel = lambda p: os.path.relpath(p, base).replace("\\", "/") if base else os.path.basename(p)
    files = sorted(set(files), key=lambda p: (os.path.getsize(p), rel(p)))
    by_size = collections.defaultdict(list)
    for p in files: by_size[os.path.getsize(p)].append(p)
    uniq = {}
    for p in files:
        r = rel(p)
        sha = (manifest_sha or {}).get(r)
        if sha is None:
            sha = sha256_file(p) if len(by_size[os.path.getsize(p)]) > 1 else f"size:{os.path.getsize(p)}"
        if sha in uniq: uniq[sha]["copies"].append(r); continue
        uniq[sha] = dict(path=p, rel=r, bytes=os.path.getsize(p), sha256=sha, copies=[])
    return sorted(uniq.values(), key=lambda c: (c["bytes"], c["rel"]))


def score_all(cands, scan, workers=None):
    """Score candidates against the STEP scan. Mutates and returns cands."""
    workers = workers or C.CANDIDATE_BATCH
    names = collections.Counter(scan["product_names"]); uuids = sorted(scan["uuids"])
    n_elements = len(uuids) if uuids else len(scan["product_names"])
    tmp = tempfile.mkdtemp(prefix="isv_"); kp = os.path.join(tmp, "keys.json")
    with open(kp, "w", encoding="utf-8") as fh: json.dump({"names": dict(names), "uuids": uuids}, fh)
    def one(i):
        c = cands[i]; op = os.path.join(tmp, f"{i}.json")
        try:
            subprocess.run([sys.executable, "-m", "ifcstepverify.score_worker", c["path"], kp, op],
                           capture_output=True, timeout=4 * 3600, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            with open(op, encoding="utf-8") as fh: c.update(json.load(fh))
        except Exception as e:
            c["error"] = f"scoring failed: {type(e).__name__}: {e}"[:300]
    try:
        with ThreadPoolExecutor(workers) as ex:
            for s in range(0, len(cands), workers):
                list(ex.map(one, range(s, min(s + workers, len(cands)))))
                if any(c.get("overlap") == 1.0 and c.get("physical_elements") == n_elements for c in cands[:s + workers]):
                    for c in cands[s + workers:]: c["not_scored"] = "a perfect source was found in an earlier batch"
                    break
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return cands


def choose(cands, scan):
    """Best source + optional combination of several IFCs (greedy, deterministic)."""
    n_elements = len(scan["uuids"]) if scan["uuids"] else len(scan["product_names"])
    ok = [c for c in cands if "overlap" in c]
    if not ok: return None, None
    best = min(ok, key=lambda c: (-c["overlap"], abs(c["physical_elements"] - n_elements), c["bytes"], c["rel"]))
    combo = None
    if best["overlap"] < 0.98 and len(ok) > 1:
        want = collections.Counter(scan["uuids"]) if scan["uuids"] else collections.Counter(scan["product_names"])
        total = max(1, sum(want.values()))
        def keys(c): return collections.Counter(c["keys"]) if isinstance(c["keys"], dict) else collections.Counter({k: 1 for k in c["keys"]})
        cover = lambda U: sum(min(U[k], want[k]) for k in want) / total
        chosen, union = [], collections.Counter()
        while True:
            gains = sorted(((cover(union + keys(c)) - cover(union), c["rel"], c) for c in ok if c not in chosen), key=lambda x: (-x[0], x[1]))
            if not gains or gains[0][0] <= 0.01: break
            chosen.append(gains[0][2]); union += keys(gains[0][2])
        if len(chosen) > 1:
            combo = dict(sources=[c["rel"] for c in chosen], coverage=round(cover(union), 6), elements=sum(c["physical_elements"] for c in chosen))
    return best, combo
