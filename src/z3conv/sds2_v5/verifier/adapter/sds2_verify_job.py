"""SDS2 'verify' final job: run sds2_step_verifier v1.3.3 (through verify_v55.py) on one converted job and apply the
class-1 rule. Read-only on the conversion: the STEP is never changed (the verifier's caches and reports go next to a
local copy / into --out; --dedup-out is never used).

usage: python sds2_verify_job.py --verifier <sds2_step_verifier dir> --job <SDS2 job dir> --step <x_stage2.step>
                                 --out <dir> [--gt <folder with SDS2's IFC / KISS / NC1>]
  The STEP's siblings <x>_pieces.csv, <x>_skipped.csv and <x>_manifest.json (converter output) must sit next to it.
Writes <out>/<x>_sds2verify.json (+ the verifier's .md / .json / _missing.csv) and prints one RESULT line.

Rule (proposed for the builder):
  - Class 1 needs, on top of the converter's own class 1: verifier verdict CORRECT or CORRECT (with warnings) and
    tier A. Verdict-making checks only: on stage-2 files the verifier itself does not count its member-decoder checks
    (D1-D6) as failures, so their FAIL does not demote.
  - Otherwise class 1 -> class 2; the reasons are the verifier's verdict, its failing checks and its missing count.
  - Classes 0 / 2 / 3 are never raised by the verifier (it is a gate, not a promotion).
  - The verdict is taken WITHOUT ground truth. E1-E3 (SDS2's IFC / KISS / NC1, when present) are run separately and
    recorded as tier_confidence and e_checks only: on Greenwood the KISS / NC1 set is from another revision of the
    job (950 studs absent from the job), so an E FAIL is evidence to review, not an automatic demotion.
"""
import os, sys, json, glob, argparse, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OK_VERDICTS = ("CORRECT", "CORRECT (with warnings)")


def run(verifier, job, step, prefix, gt_args):
    cmd = [sys.executable, os.path.join(HERE, "verify_v55.py"), "--verifier", verifier, "--job", job, "--step", step,
           "--out", prefix] + gt_args
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 or not os.path.exists(prefix + ".json"):
        return None, (p.stderr or p.stdout)[-2000:]
    return json.load(open(prefix + ".json")), None


def gt_args(gt):
    """--gt, or explicit KISS / NC1 lists when ifcopenshell (needed only for the IFC check) is not installed."""
    if not gt:
        return [], None
    try:
        import ifcopenshell  # noqa: F401
        return ["--gt", gt], None
    except ImportError:
        kss = sorted(glob.glob(os.path.join(gt, "**", "*.kss"), recursive=True))
        nc1 = sorted({os.path.dirname(f) for f in glob.glob(os.path.join(gt, "**", "*.nc1"), recursive=True)})
        a = (["--kss"] + kss if kss else []) + (["--nc1-dir", gt] if nc1 else [])
        return a, "E1 (IFC) not run: ifcopenshell not installed"


def grade(our_class, rep):
    """Pure rule: (proposed class, reasons). rep = verifier report without ground truth."""
    if our_class != 1:
        return our_class, []
    if rep is None:
        return 2, ["sds2-verify: verifier did not run (see error); class 1 needs a verifier verdict"]
    v, tier = rep["verdict"], rep["tier"]["tier"]
    if v in OK_VERDICTS and tier == "A":
        return 1, []
    stage2_soft = {"D1", "D2", "D3", "D4", "D5", "D6"} if rep.get("stage") == "piece" else set()
    fails = [f"{c['id']} {c['status']}: {c['reason']}" for c in rep["checks"] if c["status"] == "FAIL" and c["id"] not in stage2_soft]
    c1 = next((c for c in rep["checks"] if c["id"] == "C1"), {})
    miss = (c1.get("metrics") or {}).get("missing")
    why = [f"sds2-verify: verdict {v}, tier {tier}"] + fails[:8]
    if miss:
        why.append(f"sds2-verify: {miss} expected piece(s) missing (verifier _missing.csv)")
    if tier != "A" and rep["tier"].get("tier_reasons"):
        why.append("sds2-verify tier: " + "; ".join(rep["tier"]["tier_reasons"])[:400])
    return 2, why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verifier", required=True); ap.add_argument("--job", required=True); ap.add_argument("--step", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--gt")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    base = os.path.splitext(os.path.basename(a.step))[0]
    man_p = os.path.splitext(a.step)[0] + "_manifest.json"
    man = json.load(open(man_p)) if os.path.exists(man_p) else {}
    our = man.get("class")
    rep, err = run(a.verifier, a.job, a.step, os.path.join(a.out, base + "_verify"), [])
    e_checks, conf, note = {}, (rep or {}).get("tier", {}).get("tier_confidence"), None
    ga, note = gt_args(a.gt)
    if ga and rep is not None:
        rep_gt, err_gt = run(a.verifier, a.job, a.step, os.path.join(a.out, base + "_verify_gt"), ga)
        if rep_gt:
            e_checks = {c["id"]: dict(status=c["status"], reason=c["reason"], metrics=c["metrics"]) for c in rep_gt["checks"] if c["id"] in ("E1", "E2", "E3")}
            conf = rep_gt["tier"].get("tier_confidence") or conf
            if any(e["status"] == "FAIL" for e in e_checks.values()):
                conf = f"contradicted by outside evidence ({', '.join(k for k, e in e_checks.items() if e['status'] == 'FAIL')} FAIL; review: ground truth may be another revision)"
        else:
            note = (note + "; " if note else "") + f"ground-truth run failed: {err_gt[-300:]}"
    cls, why = grade(our, rep)
    out = dict(job=os.path.basename(a.job.rstrip("/")), step=os.path.basename(a.step), converter=man.get("converter"),
               our_class=our, our_corpus=man.get("corpus"), proposed_class=cls, proposed_reasons=why,
               verifier_verdict=(rep or {}).get("verdict"), verifier_tier=(rep or {}).get("tier", {}).get("tier"),
               tier_confidence=conf, e_checks=e_checks, ground_truth_note=note,
               failing_checks=[dict(id=c["id"], reason=c["reason"]) for c in (rep or {}).get("checks", []) if c["status"] == "FAIL"],
               warnings=[dict(id=c["id"], reason=c["reason"]) for c in (rep or {}).get("checks", []) if c["status"] == "WARN"],
               missing=next((c["metrics"].get("missing") for c in (rep or {}).get("checks", []) if c["id"] == "C1"), None),
               adapter=(rep or {}).get("adapter"), error=err)
    json.dump(out, open(os.path.join(a.out, base + "_sds2verify.json"), "w"), indent=1, default=str)
    print("RESULT", json.dumps({k: out[k] for k in ("job", "our_class", "proposed_class", "verifier_verdict", "verifier_tier", "tier_confidence")}))


if __name__ == "__main__":
    main()
