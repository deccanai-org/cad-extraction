"""Re-run the production decoder (db1dec + db1step, fetched from _control/db1-v2/src) on the input .db1 and compare
the model it builds with the published STEP, part for part, in the same coordinates (no alignment allowed).

This proves three things the conversion record alone cannot: the STEP named <sha>.stp really came from the .db1 with
that sha, it is what the current decoder produces (not a stale or mixed-up upload), and the IFC -> STEP step kept
every part where the decoder put it. It does not prove the decoder reads Tekla correctly; truth.py does that."""
import os, sys, json, subprocess, time, hashlib
from . import config as C
from . import s3io

SRC_FILES = ("db1dec.py", "db1step.py", "db1old.py")


def fetch_decoder(cache_dir):
    """decoder sources + profile catalog + layouts, as the production worker downloads them. -> (dir, digest)"""
    d = os.path.join(cache_dir, "decoder"); os.makedirs(d, exist_ok=True)
    h = hashlib.sha256()
    for f in SRC_FILES:
        s3io.download(C.BUCKET, f"{C.CTL_PREFIX}src/{f}", os.path.join(d, f)); h.update(open(os.path.join(d, f), "rb").read())
    for f in ("tekla_profiles.json", "layouts.json"):
        s3io.download(C.BUCKET, f"{C.CTL_PREFIX}{f}", os.path.join(d, f)); h.update(open(os.path.join(d, f), "rb").read())
    return d, h.hexdigest()[:16]


def run(db1_path, engine, work_dir, cache_dir, timeout=4 * 3600):
    """-> dict(status, stats (the decoder's own), elements=[...], secs) ; elements carry name/volume/centroid/bbox (mm)"""
    dec, digest = fetch_decoder(cache_dir)
    os.makedirs(work_dir, exist_ok=True)
    out = os.path.join(work_dir, "repro_elements.json")
    cmd = [sys.executable, "-m", "db1stepverify.repro_worker", db1_path, os.path.join(work_dir, "repro.ifc"), dec, engine or "", out]
    t0 = time.time()
    if os.path.exists(out) and os.path.getmtime(out) > os.path.getmtime(db1_path):      # resume: same input, already decoded
        r = json.load(open(out)); r["decoder_digest"] = digest; r["reused"] = True; r.setdefault("secs", r.get("decode_secs"))
        return r
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        rc = p.returncode; tail = (p.stdout + p.stderr)[-1500:]
    except subprocess.TimeoutExpired:
        return dict(status="timeout", secs=round(time.time() - t0, 1), decoder_digest=digest)
    if rc != 0 or not os.path.exists(out):
        return dict(status="error", rc=rc, log_tail=tail, secs=round(time.time() - t0, 1), decoder_digest=digest)
    r = json.load(open(out)); r["secs"] = round(time.time() - t0, 1); r["decoder_digest"] = digest
    return r
