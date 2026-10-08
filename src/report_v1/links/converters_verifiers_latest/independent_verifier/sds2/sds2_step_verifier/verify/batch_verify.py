"""Verify many conversions after the conversion pipeline has run, and write one summary table.

usage:
  python batch_verify.py jobs.csv summary.csv [--selftest] [--workers N]
jobs.csv columns: job (SDS2 job folder), step (converted STEP; empty = pre-conversion gate only),
                  gt (optional folder with IFC/KISS/NC1 for that job), ifc (optional IFC file)

Every file gets its own <step>_verify.md/.json (and <step>_verify_missing.csv when items are missing).
Rows without a step (pre-conversion gate only) write <job name>_precheck.md/.json next to summary.csv.
summary.csv has one row per file: verdict (CORRECT / CORRECT (with warnings) / INCOMPLETE / INCORRECT /
CANNOT VERIFY), the reasons, missing counts from C1, evidence level, and every check's status.
Jobs run in parallel (default: CPU count - 1).
"""
import sys, os, csv, json, subprocess, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))


def one(r, selftest, outdir, dedup_out=None):
    # pre-conversion reports go next to summary.csv, so a batch never overwrites reports from earlier runs
    prefix = (os.path.splitext(r["step"])[0] + "_verify") if r.get("step") else \
             os.path.join(outdir, os.path.basename(r["job"].rstrip("\\/")) + "_precheck")
    cmd = [sys.executable, os.path.join(HERE, "verify.py"), "--job", r["job"], "--out", prefix]
    if r.get("step"): cmd += ["--step", r["step"]]
    if r.get("gt"): cmd += ["--gt", r["gt"]]
    if r.get("ifc"): cmd += ["--ifc", r["ifc"]]
    if selftest and r.get("step"): cmd.append("--selftest")
    if dedup_out and r.get("step"): cmd += ["--dedup-out", dedup_out]
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    try:
        rep = json.load(open(prefix + ".json", encoding="utf-8"))
    except OSError:
        return dict(job=r["job"], step=r.get("step", ""), verdict="ERROR", reasons=(p.stderr or p.stdout)[-400:])
    c1 = next((c for c in rep["checks"] if c["id"] == "C1"), {}).get("metrics", {})
    tier = rep.get("tier") or {}
    row = dict(job=r["job"], step=r.get("step", ""), version=rep.get("version"), stage=rep.get("stage"),
               verdict=rep.get("verdict"), reasons=" | ".join(rep.get("verdict_reasons") or []),
               tier=tier.get("tier"), tier_confidence=tier.get("tier_confidence"), tier_reasons=" | ".join(tier.get("tier_reasons") or []),
               flagged_share=tier.get("flagged_share"), assembly_file=tier.get("assembly_file"), bolts=tier.get("bolts"),
               source_connection_plates=tier.get("source_connection_plates"),
               **{f"flag_{k}": v for k, v in (tier.get("flags") or {}).items()},
               dedup_file=(rep.get("dedup") or {}).get("file"), dedup_removed=(rep.get("dedup") or {}).get("removed"),
               dedup_readback_ok=(rep.get("dedup") or {}).get("readback_ok"),
               expected=c1.get("expected_members", c1.get("expected_pieces")), missing=c1.get("missing"), unexpected=c1.get("unexpected"),
               evidence=rep["evidence"], blind_spots="; ".join(rep.get("selftest_blind_spots") or []))
    for c in rep["checks"]:
        row[c["id"]] = c["status"]
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs"); ap.add_argument("summary")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--dedup-out", help="folder for de-duplicated STEP copies (originals are never changed)")
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.jobs, encoding="utf-8-sig")))
    out = []
    with ThreadPoolExecutor(a.workers) as ex:
        outdir = os.path.dirname(os.path.abspath(a.summary))
        futs = [ex.submit(one, r, a.selftest, outdir, a.dedup_out) for r in rows]
        for fu in as_completed(futs):
            row = fu.result(); out.append(row)
            print(f"{row['verdict']:24s} {row.get('tier') or '':14s} {row.get('missing', '')!s:>6} missing  {row['step'] or row['job']}", flush=True)
    first = ["job", "step", "version", "stage", "verdict", "tier", "tier_confidence", "reasons", "tier_reasons", "flagged_share", "expected", "missing",
             "unexpected", "evidence", "blind_spots"]
    keys = first + sorted({k for o in out for k in o} - set(first))
    with open(a.summary, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(out)
    from collections import Counter
    print("verdicts:", dict(Counter(o["verdict"] for o in out)))
    print("tiers:", dict(Counter(o.get("tier") or "ERROR" for o in out)))
    print("summary ->", a.summary)


if __name__ == "__main__":
    main()
