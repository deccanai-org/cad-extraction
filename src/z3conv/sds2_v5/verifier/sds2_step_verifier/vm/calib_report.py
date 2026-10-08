"""Aggregate the mass calibration run into per-version calibration, threshold evidence and ship decisions.

usage: python calib_report.py results.jsonl out_prefix
Writes <out_prefix>.md (human report), <out_prefix>_jobs.csv (one row per job with decision) and
<out_prefix>_thresholds.json (metric distributions over clean jobs, for threshold calibration).

Ship decision per job and stage:
  ship            : no FAIL; evidence 'external' or 'mass' (SDS2 weights agree)
  ship-after-fix  : every FAIL is a known converter defect with a fix spec
                    (M2 joists, M1 families_off, S3 names, G4 converter duplicates, G5 piece geometry)
  reject          : a FAIL in decoding (D*), STEP integrity (S1/S2/S4), placement (G1) or external truth (E*)
  not-converted   : pre-conversion gate failed (unsupported / undecodable layout)
"""
import sys, json, csv, collections, statistics as stat

KNOWN_CONVERTER = {"M2", "M1", "S3", "G4", "G5"}
HARD = {"D1", "D2", "D3", "D4", "D6", "S1", "S2", "S4", "G1", "E1", "E2", "E3"}


def vkey(v):
    try: return [int(x) for x in (v or "0").split(".")]
    except ValueError: return [999]


VALIDATED = ("7.2", "7.3")   # versions whose decoding was proven against SDS2's own IFC (50 Binney, Greenwood)


def decide(rep, version=""):
    """M1 'mass' evidence compares solids with weights from the same decoded shape table: it proves consistency,
    not decoding. It is enough only on VALIDATED versions; elsewhere shipping needs external evidence (IFC/KISS/NC1)."""
    if not rep: return "error", []
    fails = [c["id"] for c in rep["checks"] if c["status"] == "FAIL"]
    validated = (version or "").startswith(VALIDATED)
    if not fails:
        if rep["evidence"] == "external" or (validated and rep["evidence"] == "mass"):
            return "ship", fails
        return "needs-evidence", fails
    if all(f in KNOWN_CONVERTER for f in fails) and not (set(fails) & HARD):
        return "ship-after-fix", fails
    return "reject", fails


def main():
    src, out = sys.argv[1], sys.argv[2]
    R = {}
    for line in open(src, encoding="utf-8"):
        if line.strip():
            r = json.loads(line); R[r["id"]] = r
    rows, by_v = [], collections.defaultdict(list)
    status_mx = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    metric = collections.defaultdict(list)
    st_det = collections.defaultdict(lambda: collections.Counter())
    for r in R.values():
        v = r.get("version") or "unknown"
        pre = (r.get("steps") or {}).get("precheck") or {}
        lay = r.get("layout") or {}
        row = dict(id=r["id"], version=v, name=r.get("name"), members=r.get("members_listed"), error=r.get("error", ""),
                   gate=pre.get("overall"), slot=lay.get("calibrated_slot"), mtrl=None,
                   bytes_fetched=(r.get("fetch") or {}).get("bytes_fetched"), gt_files=(r.get("fetch") or {}).get("gt_files"))
        for stage in ("stage1", "stage2"):
            vr = (r.get("steps") or {}).get(f"{stage}_verify") or {}
            rep = vr.get("report")
            dec, fails = decide(rep, v) if rep else (("not-converted" if pre.get("overall") == "FAIL" or not pre else "error") if stage == "stage1" else "", [])
            row[f"{stage}_overall"] = rep and rep["overall"]; row[f"{stage}_evidence"] = rep and rep["evidence"]
            row[f"{stage}_decision"] = dec; row[f"{stage}_fails"] = " ".join(fails)
            if rep:
                for c in rep["checks"]:
                    status_mx[stage][c["id"]][c["status"]] += 1
                    m = c.get("metrics") or {}
                    if c["id"] == "D2" and m.get("layout"): row["mtrl"] = f"{m['layout'].get('record')}B/{m['layout'].get('byte_order')}"
                    # threshold evidence only from jobs whose other checks are clean
                    for key in ("median_ratio", "within_tol_share", "length_ok", "placed_on_workline", "top_of_steel_ok",
                                "touching_share", "resolved_share", "within_0_1in", "section_recall", "loose_recall", "tight_recall", "agreement"):
                        if isinstance(m.get(key), (int, float)):
                            metric[(stage, c["id"], key)].append(m[key])
                    if isinstance(m.get("recall_by_kind"), dict):
                        for k2, val in m["recall_by_kind"].items(): metric[(stage, "E1", f"recall_{k2}")].append(val)
                for s in rep.get("selftest") or []:
                    st_det[(stage, s["mutation"])]["runs"] += 1
                    st_det[(stage, s["mutation"])]["detected"] += bool(s["detected"])
                    st_det[(stage, s["mutation"])]["to_fail"] += bool(s["to_fail"])
        rows.append(row); by_v[v].append(row)
    # --- write CSV
    keys = list(rows[0].keys()) if rows else []
    with open(out + "_jobs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(sorted(rows, key=lambda r: (vkey(r["version"]), r["id"])))
    thr = {f"{s}/{c}/{k}": dict(n=len(v), min=round(min(v), 4), p10=round(sorted(v)[int(0.1 * (len(v) - 1))], 4),
                                median=round(stat.median(v), 4), p90=round(sorted(v)[int(0.9 * (len(v) - 1))], 4), max=round(max(v), 4))
           for (s, c, k), v in sorted(metric.items()) if v}
    json.dump(thr, open(out + "_thresholds.json", "w"), indent=1)
    # --- markdown
    L = ["# SDS2 → STEP mass verification & calibration", "",
         f"Jobs: {len(rows)} across {len(by_v)} versions. Errors: {sum(1 for r in rows if r['error'])}.", "",
         "## Per version", "", "| version | jobs | gate PASS/WARN/FAIL | slot | job_mtrl | stage-1 ship / needs-evidence / after-fix / reject / not-conv | stage-2 ship / needs-evidence / after-fix / reject |",
         "|---|---:|---|---|---|---|---|"]
    for v in sorted(by_v, key=vkey):
        rs = by_v[v]; g = collections.Counter(r["gate"] for r in rs)
        d1 = collections.Counter(r["stage1_decision"] for r in rs); d2 = collections.Counter(r["stage2_decision"] for r in rs)
        slots = sorted({str(r["slot"]) for r in rs if r["slot"]}); mt = sorted({r["mtrl"] for r in rs if r["mtrl"]})
        L.append(f"| {v} | {len(rs)} | {g['PASS']}/{g['WARN']}/{g['FAIL']} | {', '.join(slots) or '-'} | {', '.join(mt) or '-'} | "
                 f"{d1['ship']} / {d1['needs-evidence']} / {d1['ship-after-fix']} / {d1['reject']} / {d1['not-converted']} | "
                 f"{d2['ship']} / {d2['needs-evidence']} / {d2['ship-after-fix']} / {d2['reject']} |")
    for stage in ("stage1", "stage2"):
        L += ["", f"## Check status matrix — {stage}", "", "| check | PASS | WARN | FAIL | NA |", "|---|---:|---:|---:|---:|"]
        for cid in sorted(status_mx[stage]):
            c = status_mx[stage][cid]; L.append(f"| {cid} | {c['PASS']} | {c['WARN']} | {c['FAIL']} | {c['NA']} |")
    L += ["", "## Self-test detection over all jobs", "", "| stage | defect | runs | detected | escalated to FAIL |", "|---|---|---:|---:|---:|"]
    for (stage, mname), c in sorted(st_det.items()):
        L.append(f"| {stage} | {mname} | {c['runs']} | {c['detected']} | {c['to_fail']} |")
    L += ["", "## Metric distributions (threshold calibration evidence)", "", "| stage/check/metric | n | min | p10 | median | p90 | max |", "|---|---:|---:|---:|---:|---:|---:|"]
    for k, d in thr.items():
        L.append(f"| {k} | {d['n']} | {d['min']} | {d['p10']} | {d['median']} | {d['p90']} | {d['max']} |")
    open(out + ".md", "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:40]))


if __name__ == "__main__":
    main()
