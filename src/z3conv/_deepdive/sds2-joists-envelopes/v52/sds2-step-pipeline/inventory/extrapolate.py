"""Estimate how many Disk-2 archives convert to STEP, from the sample folder (archive-level) plus earlier job samples.

Each archive is assigned to the best SDS2 version family among its jobs (per disk2_models.csv, jsetup version;
'2015.xx'-labelled jobs are 7.4xx inside). Per family, the share of archives reaching stage2 / at least stage1 is
taken from the sample folder where it covers that family, else from the job samples (disk2_convertibility*.jsonl),
and applied to every archive in that family, whatever its size. 95% Wilson intervals.
usage: python extrapolate.py <folder_eval.jsonl> <folder_family>
"""
import os, sys, json, csv, math, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "decode"))
from preflight import verdict

INV = os.path.dirname(os.path.abspath(__file__))
RANK = {"stage2": 3, "stage1": 2, "no": 1, "error": 0}
ORDER = ["7.4xx", "7.3xx", "7.2xx", "7.6xx", "7.5xx", "unknown", "7.1xx", "7.0xx"]   # preference when mixed


def fam(v):
    if not v: return "unknown"
    if v.startswith("2015"): return "7.4xx"
    return v[:3] + "xx"


def wilson(k, n, z=1.96):
    if n == 0: return (0.0, 1.0)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - h) / d), min(1.0, (c + h) / d)


def main():
    feval, ffam = sys.argv[1], sys.argv[2]
    recs = {}
    for line in open(os.path.join(INV, "disk2_archives.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r["key"] not in recs or "error" in recs[r["key"]]:
            recs[r["key"]] = r
    ext = lambda a: os.path.splitext(a)[1].lower()
    rows = [r for r in csv.DictReader(open(os.path.join(INV, "disk2_models.csv"), encoding="utf-8")) if r["source"] == "archive"]
    fams = collections.defaultdict(set)
    for r in rows: fams[r["archive"]].add(fam(r["version"]))
    arch_fam = {a: min(fs, key=ORDER.index) for a, fs in fams.items()}

    # rates: sample folder (archive level, re-scored with the current verdict rules)
    folder = [json.loads(l) for l in open(feval, encoding="utf-8")]
    def best(a):
        vs = [verdict(j) if j.get("verdict") != "error" else "error" for j in a.get("jobs", [])]
        return max(vs, key=lambda v: RANK[v]) if vs else "none"
    fk = [best(a) for a in folder if a["n_jobs"] > 0 and best(a) != "error"]
    rates = {ffam: (sum(v == "stage2" for v in fk), sum(v in ("stage2", "stage1") for v in fk), len(fk), "sample folder (all archives)")}
    # other families: job samples
    js = [json.loads(l) for f in ("disk2_convertibility.jsonl", "disk2_convertibility2.jsonl") if os.path.exists(os.path.join(INV, f))
          for l in open(os.path.join(INV, f), encoding="utf-8")]
    by = collections.defaultdict(list)
    for r in js:
        if r.get("verdict") == "error": continue
        f = "unknown" if r["version_csv"] == "unknown" else fam(r.get("version") or r["version_csv"])
        by[f].append(verdict(r))
    for f, vs in by.items():
        if f not in rates:
            rates[f] = (sum(v == "stage2" for v in vs), sum(v in ("stage2", "stage1") for v in vs), len(vs), "job samples (non-test, >=100 members)")

    # 7.1xx: decoded since; the 7 test jobs (7.132/7.135, fetch_testset.py) all convert at stage 2 with --verify.
    # Their job-sample records above predate that (converter refused), so use the test-set result instead.
    rates["7.1xx"] = (7, 7, 7, "7.1 test set: 7 jobs converted end to end (stage 2)")
    # 7.5xx / 7.6xx: 1024-B piece table decoded since; 9 test jobs (testset_756.json) all pass preflight at stage 2
    rates["7.5xx"] = (3, 3, 3, "7.5 test set: 3 jobs (7.516) stage 2")
    rates["7.6xx"] = (6, 6, 6, "7.6 test set: 6 jobs (7.605/7.613) stage 2")
    # 7.0xx: decoded since (384-B piece table, 1280-B member slots); SUNY 7.021 + two RCMS 7.039 copies convert at stage 2
    rates["7.0xx"] = (3, 3, 3, "7.0 test set: 3 jobs converted end to end (stage 2)")
    # unknown-version archives: classified individually from their .7z listings (fingerprint.py, classify_unknown.py);
    # the share predicted convertible, times the share of validation conversions that succeeded
    cls_p, val_p = os.path.join(INV, "unknown_classified.csv"), os.path.join(INV, "unknown_validation.jsonl")
    if os.path.exists(cls_p):
        per = {}
        for r in csv.DictReader(open(cls_p, encoding="utf-8")):
            per.setdefault(r["archive"], set()).add(r["status"])
        conv = sum("convertible" in s for s in per.values())
        v = [json.loads(l) for l in open(val_p, encoding="utf-8")] if os.path.exists(val_p) else []
        ok = sum(1 for x in v if x.get("valid") and x["valid"].split("/")[0] == x["valid"].split("/")[1])
        pass_rate = ok / len(v) if v else 1.0
        n = len(per); k = round(conv * pass_rate)
        rates["unknown"] = (k, k, n, f"listings classified: {conv}/{n} archives convertible x validation {ok}/{len(v)}")
    print("rates per family (stage2 / stage1+ / n, source):")
    for f in ORDER:
        if f in rates: print(f"  {f:8s} {rates[f][0]:3d} / {rates[f][1]:3d} / {rates[f][2]:3d}  {rates[f][3]}")
    tot = collections.Counter(); tot_lo = collections.Counter(); tot_hi = collections.Counter()
    print("\n| family | .zip | .7z | est. stage 2 | est. stage 1 or better |\n|---|---:|---:|---:|---:|")
    for f in ORDER:
        A = [a for a, g in arch_fam.items() if g == f]
        if not A: continue
        nz = sum(ext(a) == ".zip" for a in A); n7 = sum(ext(a) == ".7z" for a in A)
        s2, s1, n, _ = rates.get(f, (0, 0, 0, ""))
        cells = []
        for k, key in ((s2, "s2"), (s1, "s1")):
            p = k / n if n else 0.0; lo, hi = wilson(k, n)
            for e, cnt in ((".zip", nz), (".7z", n7)):
                tot[key, e] += p * cnt; tot_lo[key, e] += lo * cnt; tot_hi[key, e] += hi * cnt
            cells.append(f"{p * len(A):.0f} ({lo * len(A):.0f}–{hi * len(A):.0f})" if n else "not sampled")
        print(f"| {f} | {nz} | {n7} | {cells[0]} | {cells[1]} |")
    for key, label in (("s2", "stage 2"), ("s1", "stage 1 or better")):
        print(f"\nTOTAL {label}: .zip {tot[key, '.zip']:.0f} ({tot_lo[key, '.zip']:.0f}–{tot_hi[key, '.zip']:.0f}), "
              f".7z {tot[key, '.7z']:.0f} ({tot_lo[key, '.7z']:.0f}–{tot_hi[key, '.7z']:.0f}), "
              f"all {tot[key, '.zip'] + tot[key, '.7z']:.0f} ({tot_lo[key, '.zip'] + tot_lo[key, '.7z']:.0f}–{tot_hi[key, '.zip'] + tot_hi[key, '.7z']:.0f})"
              f" of {len(arch_fam)} archives with SDS2 jobs")


if __name__ == "__main__":
    main()
