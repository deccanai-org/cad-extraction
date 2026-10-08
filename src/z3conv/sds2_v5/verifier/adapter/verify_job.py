"""SDS2 verify job (same interface as the IFC / DB1 verifier adapters).

usage: python verify_job.py --pipeline sds2 --row <index-row JSON | file with it | job id> --out <result.json>
                            [--verifier <sds2_step_verifier dir>] [--work <scratch dir>] [--keep]

Downloads (read-only, bucket bim-proprietary-data, default AWS credentials) the converted STEP named by the row's
step_key (an id alone: the fleet result record's step key) with its _pieces.csv / _skipped.csv / _manifest.json, the
SDS2 job's model files (main / mem / subm, from the fleet's files manifest), and any SDS2 IFC export / KISS / NC1
files inside the job folder. Runs sds2_step_verifier v1.3.3 through verify_v55.py (format adapter), once without
ground truth (the verdict) and, when ground-truth files exist, once with them (E1-E3 -> tier_confidence only).
Published STEPs never change: everything is a local copy in --work; the verifier's dedup copies are never made.

Output JSON: {pipeline, id, step_key, step_etag, verifier, verifier_version, verdict PASS|WARN|FAIL|CANNOT_VERIFY|ERROR,
evidence external_truth|independent_decode|integrity, findings [{code, level, cause, count, detail}], missing [cap 200]
(+ <out>_missing.csv), tier, tier_confidence, runtime_s, peak_gb, class1_ok, class1_reasons, ...}
  verdict: CORRECT -> PASS, CORRECT (with warnings) -> WARN, INCOMPLETE / INCORRECT -> FAIL, CANNOT VERIFY -> CANNOT_VERIFY.
  findings: one per check that is not PASS / NA. level WARN / FAIL as the verifier graded it; NOTE for results the
    verifier itself does not count in the verdict (its member-decoder checks D1-D6 on stage-2 files) and for E1-E3
    (ground truth: tier_confidence only). cause: converter | source | by_design | verifier | external_truth (CAUSE).
  class-1 rule: verdict PASS, or WARN where every WARN finding's cause is source or by_design; no FAIL; tier A.
"""
import os, sys, re, csv, json, glob, gzip, time, shutil, argparse, resource, subprocess, collections
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
BUCKET = "bim-proprietary-data"
STATE = "cad-disk-extract/zenitude-data-3/_state/conv/sds2/"
VERIFIER_VERSION = "1.3.3+verify_v55"
VERDICT = {"CORRECT": "PASS", "CORRECT (with warnings)": "WARN", "INCOMPLETE": "FAIL", "INCORRECT": "FAIL",
           "CANNOT VERIFY": "CANNOT_VERIFY"}
MODEL_DIRS = ("main", "mem", "subm", "pcm")
GT_EXT = {".ifc": "ifc", ".kss": "kss", ".nc1": "nc1"}


def s3c():
    import boto3
    return boto3.client("s3", region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-south-1"))


def load_row(arg, s3):
    if os.path.exists(arg):
        return json.load(open(arg))
    if arg.lstrip().startswith("{"):
        return json.loads(arg)
    rec = json.loads(s3.get_object(Bucket=BUCKET, Key=f"{STATE}results/{arg}.json")["Body"].read())
    return dict(pipeline="sds2", id=arg, step_key=(rec.get("step") or {}).get("key"), version=rec.get("version"))


def fetch_job(s3, jid, dest):
    """Model files from the fleet's files manifest, plus IFC / KISS / NC1 files found under the job folder itself."""
    lst = s3.list_objects_v2(Bucket=BUCKET, Prefix=f"{STATE}files/{jid}").get("Contents") or []
    if not lst:
        raise RuntimeError(f"no files manifest for {jid}")
    body = s3.get_object(Bucket=BUCKET, Key=lst[0]["Key"])["Body"].read()
    try:
        body = gzip.decompress(body)
    except OSError:
        pass
    mf = json.loads(body)
    jobdir = os.path.join(dest, "job"); gtdir = os.path.join(dest, "gt")

    def one(f):
        parts = [p.lower() if p.lower() in MODEL_DIRS + ("job_mtrl", "mem_idx", "subm_idx", "jsetup") else p
                 for p in f["p"].replace("\\", "/").split("/") if p]
        path = os.path.join(jobdir, *parts); os.makedirs(os.path.dirname(path), exist_ok=True)
        if not f.get("key"):
            open(path, "wb").close(); return
        s3.download_file(BUCKET, f["key"], path)
    with ThreadPoolExecutor(16) as ex:
        list(ex.map(one, mf))
    # ground truth inside the job folder: same storage roots as the model files (root = key minus its relative path)
    roots = {f["key"][:-len(f["p"])] for f in mf if f.get("key") and f["key"].endswith(f["p"])}
    gt = collections.defaultdict(list)
    for root in sorted(roots)[:4]:
        for pg in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=root):
            for o in pg.get("Contents", []):
                ext = os.path.splitext(o["Key"])[1].lower()
                if ext in GT_EXT and len(gt[GT_EXT[ext]]) < 2000:
                    rel = o["Key"][len(root):]
                    p = os.path.join(gtdir, os.path.splitext(rel)[0] + ext)      # lower-case extension for the verifier
                    if not os.path.exists(p):
                        os.makedirs(os.path.dirname(p), exist_ok=True); s3.download_file(BUCKET, o["Key"], p)
                        gt[GT_EXT[ext]].append(p)
    return jobdir, (gtdir if gt else None), {k: len(v) for k, v in gt.items()}


def fetch_step(s3, key, dest):
    os.makedirs(dest, exist_ok=True)
    head = s3.head_object(Bucket=BUCKET, Key=key)
    step = os.path.join(dest, os.path.basename(key)); s3.download_file(BUCKET, key, step)
    base = key[:-len(".step")] if key.endswith(".step") else os.path.splitext(key)[0]
    for suf in ("_manifest.json", "_pieces.csv", "_skipped.csv", "_members.csv"):
        try:
            s3.download_file(BUCKET, base + suf, os.path.join(dest, os.path.basename(base + suf)))
        except Exception:
            pass
    return step, head.get("ETag", "").strip('"')


def run_verifier(verifier, job, step, prefix, extra):
    cmd = [sys.executable, os.path.join(HERE, "verify_v55.py"), "--verifier", verifier, "--job", job, "--step", step,
           "--out", prefix] + extra
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 or not os.path.exists(prefix + ".json"):
        return None, (p.stderr or p.stdout)[-1500:]
    return json.load(open(prefix + ".json")), None


def cause(c, stage):
    """Where a non-PASS check result comes from (documented mapping; conservative: unexplained -> converter)."""
    cid, m, reason = c["id"], c.get("metrics") or {}, c.get("reason") or ""
    if cid.startswith("E"):
        return "external_truth"
    if cid.startswith("D"):
        return "source" if cid == "D5" else "verifier"            # D5: stray members kept in the SDS2 job
    if cid == "S2" and c["status"] == "WARN" and "multi-body" in reason:
        return "by_design"                                         # valid, closed multi-body SDS2 pieces (anchors, studs)
    if cid == "M2" and c["status"] == "WARN" and "no recorded weight" in reason:
        return "source"
    if cid == "G4" and not m.get("introduced_by_converter") and m.get("already_in_sds2_job"):
        return "source"
    return "converter"


def level(c, stage):
    if c["id"].startswith("E"):
        return "NOTE"
    if stage == "piece" and c["id"] in ("D1", "D2", "D3", "D4", "D5", "D6"):
        return "NOTE"                                              # the verifier skips these for stage-2 verdicts
    return c["status"]


def count_of(c):
    m = c.get("metrics") or {}
    for k in ("missing", "introduced_by_converter", "isolated", "off_parent", "unexpected", "outliers"):
        if m.get(k):
            return int(m[k])
    return None


def main():
    t0 = time.time()
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", required=True); ap.add_argument("--row", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--verifier", default=os.path.join(HERE, "..", "sds2_step_verifier"))
    ap.add_argument("--work"); ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    if a.pipeline != "sds2":
        sys.exit("this adapter handles --pipeline sds2 only")
    s3 = s3c()
    row = load_row(a.row, s3)
    jid, key = row.get("id"), row.get("step_key")
    work = a.work or os.path.join(os.path.dirname(os.path.abspath(a.out)), f".sds2verify_{jid}")
    res = dict(pipeline="sds2", id=jid, step_key=key, step_etag=None, verifier="sds2_step_verifier",
               verifier_version=VERIFIER_VERSION, verdict="ERROR", evidence="integrity", findings=[], missing=[],
               tier=None, tier_confidence=None, runtime_s=None, peak_gb=None)
    try:
        if not key:
            raise RuntimeError("row has no step_key (nothing converted)")
        step, res["step_etag"] = fetch_step(s3, key, os.path.join(work, "step"))
        job, gt, gt_counts = fetch_job(s3, jid, work)
        man_p = os.path.splitext(step)[0] + "_manifest.json"
        man = json.load(open(man_p)) if os.path.exists(man_p) else {}
        res.update(converter=man.get("converter"), converter_class=man.get("class"), converter_corpus=man.get("corpus"),
                   ground_truth_files=gt_counts)
        rep, err = run_verifier(a.verifier, job, step, os.path.join(work, "verify"), [])
        if rep is None:
            raise RuntimeError(f"verifier failed: {err}")
        stage = rep.get("stage")
        res["verdict"] = VERDICT.get(rep["verdict"], "ERROR")
        res["verifier_verdict"] = rep["verdict"]
        res["tier"] = rep["tier"]["tier"]; res["tier_confidence"] = rep["tier"].get("tier_confidence")
        res["tier_reasons"] = rep["tier"].get("tier_reasons"); res["adapter"] = rep.get("adapter")
        checks = list(rep["checks"])
        e_pass = False
        if gt:
            extra = ["--gt", gt]
            try:
                import ifcopenshell  # noqa: F401
            except ImportError:
                kss = sorted(glob.glob(os.path.join(gt, "**", "*.kss"), recursive=True))
                extra = (["--kss"] + kss if kss else []) + (["--nc1-dir", gt] if glob.glob(os.path.join(gt, "**", "*.nc1"), recursive=True) else [])
                res["ground_truth_note"] = "E1 (IFC) not run: ifcopenshell not installed"
            if extra:
                rep_gt, err_gt = run_verifier(a.verifier, job, step, os.path.join(work, "verify_gt"), extra)
                if rep_gt:
                    E = [c for c in rep_gt["checks"] if c["id"] in ("E1", "E2", "E3")]
                    checks = [c for c in checks if c["id"] not in ("E1", "E2", "E3")] + E
                    e_pass = any(c["status"] == "PASS" for c in E)
                    fails = [c["id"] for c in E if c["status"] == "FAIL"]
                    if fails:
                        res["tier_confidence"] = f"contradicted by outside evidence ({', '.join(fails)} FAIL; review: ground truth may be another revision)"
                    elif e_pass and res["tier"] not in (None, "EXCLUDED"):
                        res["tier_confidence"] = rep_gt["tier"].get("tier_confidence")
                else:
                    res["ground_truth_note"] = f"ground-truth run failed: {err_gt[-300:]}"
        c1 = next((c for c in checks if c["id"] == "C1"), {})
        decoded = (c1.get("metrics") or {}).get("expected_pieces") or (c1.get("metrics") or {}).get("expected_members")
        res["evidence"] = "external_truth" if e_pass else ("independent_decode" if decoded else "integrity")
        for c in checks:
            if c["status"] in ("PASS", "NA"):
                continue
            mt = {k: v for k, v in (c.get("metrics") or {}).items() if not isinstance(v, (list, dict))}
            res["findings"].append(dict(code=c["id"], level=level(c, stage), cause=cause(c, stage), count=count_of(c),
                                        detail=f"{c['id']} {c['status']}: {c.get('title', '')}. {c.get('reason') or ''} | {json.dumps(mt)[:400]}"))
        mp = os.path.join(work, "verify_missing.csv")
        if os.path.exists(mp):
            rows = list(csv.DictReader(open(mp, encoding="utf-8")))
            res["missing"] = rows[:200]; res["missing_total"] = len(rows)
            shutil.copy(mp, os.path.splitext(a.out)[0] + "_missing.csv")
        warn_bad = [f for f in res["findings"] if f["level"] == "WARN" and f["cause"] not in ("source", "by_design")]
        fail = [f for f in res["findings"] if f["level"] == "FAIL"]
        ok = res["verdict"] in ("PASS", "WARN") and not fail and not warn_bad and res["tier"] == "A"
        res["class1_ok"] = ok
        res["class1_reasons"] = [] if ok else (
            [f"sds2-verify verdict {res['verdict']} ({rep['verdict']}), tier {res['tier']}"]
            + [f["detail"][:300] for f in fail + warn_bad][:8]
            + ([f"{res.get('missing_total')} expected piece(s) missing (see _missing.csv)"] if res.get("missing_total") else []))
    except Exception as ex:
        res["error"] = f"{type(ex).__name__}: {ex}"[:2000]
        res["class1_ok"] = False; res["class1_reasons"] = [f"sds2-verify ERROR: {res['error'][:300]}"]
    ru = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    res["peak_gb"] = round(ru / (1 << 30) if sys.platform == "darwin" else ru / (1 << 20), 2)
    res["runtime_s"] = round(time.time() - t0, 1)
    json.dump(res, open(a.out, "w"), indent=1, default=str)
    if not a.keep:
        shutil.rmtree(work, ignore_errors=True)
    print("RESULT", json.dumps({k: res.get(k) for k in ("id", "verdict", "evidence", "tier", "tier_confidence", "class1_ok",
                                                         "converter_class", "runtime_s", "peak_gb")}))


if __name__ == "__main__":
    main()
