"""SDS2 verifier adapter (builder contract): sds2_step_verifier v1.3.3 on one staged SDS2 conversion.

call: PY adapter_sds2.py --step <local STEP> --source <local SDS2 job dir> --out <json> --id <id> --workdir <dir>
                         [--gt-dir <dir with SDS2's IFC export / KISS / NC1>]
  - The STEP's converter siblings <x>_pieces.csv, <x>_skipped.csv, <x>_manifest.json must be staged next to it
    (piece manifest: S1 count, stand-in tags, converter skip reasons). Without them the verifier still runs, weaker.
  - --source: the job's model files (main/ mem/ subm/, as the fleet's files manifest stages them).
  - --gt-dir (optional): ground truth. The fleet's job folders hold model files only; sds2/stage_gt.py lists IFC /
    KISS / NC1 files stored under the same job folder in the source and stages them.
  - Package dir: sds2/ next to this file (sds2_step_verifier v1.3.3 unmodified + verify_v55.py format adapter).
  - Read-only on the conversion: the STEP is copied into --workdir and the verifier works on the copy; dedup copies
    are never made.

writes --out: {verdict PASS|WARN|FAIL|CANNOT_VERIFY|ERROR, evidence external_truth|independent_decode|integrity,
  findings [{code, level, cause, count, detail}], missing [cap 200], missing_csv (local path in --workdir, full list),
  tier, tier_confidence, verifier_verdict, class1_ok, class1_reasons, adapter, ground_truth}
  verdict: CORRECT -> PASS, CORRECT (with warnings) -> WARN, INCOMPLETE / INCORRECT -> FAIL, CANNOT VERIFY -> CANNOT_VERIFY.
  findings: every check not PASS / NA, plus the results the grading policy (sds2/verify_v55.py, decided 2026-10-02)
    records as NOTE (audit only, outside the verdict and the tier): stage-2 member-decoder checks D1-D6, C1 when every
    missing piece is listed by the converter, G2 / G3, M2 on SDS2 placeholder joist weights, E2 / E3 against ground
    truth of another revision. cause: pipeline | source | by_design | verifier | ground_truth_other_revision.
    G4 is split: converter-made repeats FAIL (pipeline), SDS2's own duplicate placements WARN (source). M1 is judged on
    the parts claimed exact. E-check FAILs against same-revision truth stay FAIL (pipeline).
  class1_ok: verdict PASS, or WARN where every WARN finding's cause is source or by_design; no FAIL; tier A.
"""
import os, sys, csv, json, glob, shutil, argparse, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "sds2")
VERDICT = {"CORRECT": "PASS", "CORRECT (with warnings)": "WARN", "INCOMPLETE": "FAIL", "INCORRECT": "FAIL",
           "CANNOT VERIFY": "CANNOT_VERIFY"}
STAGE2_SOFT = ("D1", "D2", "D3", "D4", "D5", "D6")


def run_verifier(job, step, prefix, extra):
    cmd = [sys.executable, os.path.join(PKG, "verify_v55.py"), "--verifier", os.path.join(PKG, "sds2_step_verifier"),
           "--job", job, "--step", step, "--out", prefix] + extra
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 or not os.path.exists(prefix + ".json"):
        return None, (p.stderr or p.stdout)[-1500:]
    return json.load(open(prefix + ".json")), None


def cause(c):
    """Where a non-PASS result comes from: the policy's cause when it set one; conservative default: pipeline."""
    cid, m, reason = c["id"], c.get("metrics") or {}, c.get("reason") or ""
    pol = m.get("policy") if isinstance(m.get("policy"), dict) else None
    if pol and pol.get("cause"):
        return pol["cause"]
    if cid.startswith("D"):
        return "source" if cid == "D5" else "verifier"     # D5: stray members kept in the SDS2 job; others: its decoder
    if cid == "S2" and c["status"] == "WARN" and "multi-body" in reason:
        return "by_design"                                  # valid, closed multi-body SDS2 pieces (headed anchors, studs)
    return "pipeline"


def level(c, stage):
    pol = (c.get("metrics") or {}).get("policy")
    if isinstance(pol, dict) and pol.get("level") == "NOTE":
        return "NOTE"
    if stage == "piece" and c["id"] in STAGE2_SOFT and c["status"] in ("WARN", "FAIL") and c["id"] not in ("D1", "D2"):
        return "NOTE"
    return c["status"]


def is_finding(c):
    pol = (c.get("metrics") or {}).get("policy")
    return c["status"] not in ("PASS", "NA") or (isinstance(pol, dict) and pol.get("level") == "NOTE")


def count_of(c):
    m = c.get("metrics") or {}
    for k in ("missing", "introduced_by_converter", "isolated", "off_parent", "unexpected", "outliers", "over_12in"):
        if m.get(k):
            return int(m[k])
    return None


def gt_args(gt):
    if not gt or not os.path.isdir(gt):
        return [], None
    files = [f for f in glob.glob(os.path.join(gt, "**", "*"), recursive=True) if os.path.isfile(f)]
    ifc = [f for f in files if f.lower().endswith(".ifc")]
    kss = [f for f in files if f.lower().endswith(".kss")]
    nc1 = [f for f in files if f.lower().endswith(".nc1")]
    note = None
    a = []
    if ifc:
        try:
            import ifcopenshell  # noqa: F401
            a += ["--ifc", ifc[0]]
        except ImportError:
            note = "E1 (IFC) not run: ifcopenshell not installed"
    if kss:
        a += ["--kss"] + kss
    if nc1:
        d = os.path.dirname(nc1[0]) if len({os.path.dirname(f) for f in nc1}) == 1 else gt
        if any(not f.endswith(".nc1") for f in nc1):       # the verifier globs '*.nc1' (lower case)
            d = os.path.join(os.path.dirname(gt.rstrip("/")), os.path.basename(gt.rstrip("/")) + "_nc1")
            os.makedirs(d, exist_ok=True)
            for f in nc1:
                shutil.copy(f, os.path.join(d, os.path.splitext(os.path.basename(f))[0] + ".nc1"))
        a += ["--nc1-dir", d]
    return a, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", required=True); ap.add_argument("--source", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--id"); ap.add_argument("--workdir", required=True); ap.add_argument("--gt-dir")
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    res = dict(verdict="ERROR", evidence="integrity", findings=[], missing=[], missing_csv=None, tier=None, tier_confidence=None)
    try:
        # work on a copy: the verifier writes caches / reports next to the STEP it reads
        sd = os.path.join(a.workdir, "step"); os.makedirs(sd, exist_ok=True)
        stem = os.path.splitext(a.step)[0]
        step = os.path.join(sd, os.path.basename(a.step))
        if not os.path.exists(step):
            try:
                os.link(a.step, step)
            except OSError:
                shutil.copy(a.step, step)
        for suf in ("_pieces.csv", "_skipped.csv", "_manifest.json", "_members.csv"):
            if os.path.exists(stem + suf):
                shutil.copy(stem + suf, os.path.splitext(step)[0] + suf)
        man_p = os.path.splitext(step)[0] + "_manifest.json"
        man = json.load(open(man_p)) if os.path.exists(man_p) else {}
        res.update(converter=man.get("converter"), converter_class=man.get("class"), converter_corpus=man.get("corpus"))
        extra, note = gt_args(a.gt_dir)
        res["ground_truth"] = dict(args=bool(extra), note=note)
        rep, err = run_verifier(a.source, step, os.path.join(a.workdir, "verify"), extra)
        if rep is None:
            raise RuntimeError(f"verifier failed: {err}")
        stage = rep.get("stage")
        res.update(verdict=VERDICT.get(rep["verdict"], "ERROR"), verifier_verdict=rep["verdict"], stage=stage,
                   tier=rep["tier"]["tier"], tier_confidence=rep["tier"].get("tier_confidence"),
                   tier_reasons=rep["tier"].get("tier_reasons"), adapter=rep.get("adapter"))
        checks = list(rep["checks"])
        E = [c for c in checks if c["id"] in ("E1", "E2", "E3")]
        e_pass = any(c["status"] == "PASS" for c in E)
        res["ground_truth"]["checks"] = {c["id"]: c["status"] if c["status"] != "NA" or not (c.get("metrics") or {}).get("policy")
                                         else "NOTE" for c in E}
        fails = [c["id"] for c in E if c["status"] == "FAIL"]
        if fails:
            res["tier_confidence"] = f"contradicted by outside evidence ({', '.join(fails)} FAIL against same-revision truth)"
        c1 = next((c for c in checks if c["id"] == "C1"), {})
        decoded = (c1.get("metrics") or {}).get("expected_pieces") or (c1.get("metrics") or {}).get("expected_members")
        res["evidence"] = "external_truth" if e_pass else ("independent_decode" if decoded else "integrity")
        for c in checks:
            if not is_finding(c):
                continue
            mt = {k: v for k, v in (c.get("metrics") or {}).items() if not isinstance(v, (list, dict))}
            res["findings"].append(dict(code=c["id"], level=level(c, stage), cause=cause(c), count=count_of(c),
                                        detail=f"{c['id']} {c['status']}: {c.get('title', '')}. {c.get('reason') or ''} | {json.dumps(mt)[:400]}"))
        mp = os.path.join(a.workdir, "verify_missing.csv")
        if os.path.exists(mp):
            rows = list(csv.DictReader(open(mp, encoding="utf-8")))
            res.update(missing=rows[:200], missing_total=len(rows), missing_csv=mp)
        bad_warn = [f for f in res["findings"] if f["level"] == "WARN" and f["cause"] not in ("source", "by_design")]
        fail = [f for f in res["findings"] if f["level"] == "FAIL"]
        ok = res["verdict"] in ("PASS", "WARN") and not fail and not bad_warn and res["tier"] == "A"
        res["class1_ok"] = ok
        res["class1_reasons"] = [] if ok else (
            [f"sds2-verify verdict {res['verdict']} ({rep['verdict']}), tier {res['tier']}"]
            + [f["detail"][:300] for f in fail + bad_warn][:8]
            + ([f"{res['missing_total']} expected piece(s) missing (missing_csv)"] if res.get("missing_total") else []))
    except Exception as ex:
        res["error"] = f"{type(ex).__name__}: {ex}"[:2000]
        res["class1_ok"] = False; res["class1_reasons"] = [f"sds2-verify ERROR: {res['error'][:300]}"]
    if a.id:
        res["id"] = a.id
    json.dump(res, open(a.out, "w"), indent=1, default=str)
    print("RESULT", json.dumps({k: res.get(k) for k in ("id", "verdict", "evidence", "tier", "tier_confidence", "class1_ok", "converter_class")}))


if __name__ == "__main__":
    main()
