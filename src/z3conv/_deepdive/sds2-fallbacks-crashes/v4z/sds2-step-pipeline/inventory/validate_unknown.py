"""Validate the size-fingerprint predictions: per predicted family, take the smallest archives whose job is predicted
convertible, download, extract that job, run the full stage-2 conversion with --verify, and compare the prediction
with the job's actual jsetup version and the conversion result.
usage: python validate_unknown.py unknown_classified.csv <workdir> <out.jsonl> [per_family] [budget_mb]
"""
import os, sys, csv, json, re, shutil, subprocess, collections
import boto3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sample_convertibility import extract

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "decode", "sds2_to_step.py")
OUT = os.path.join(ROOT, "out", "samples_unknown")
FAM = {"7.0": "7.0xx", "7.1": "7.1xx", "7.2": "7.2xx", "7.3": "7.3xx", "7.4": "7.4xx", "7.5": "7.5/7.6xx", "7.6": "7.5/7.6xx"}

if __name__ == "__main__":
    rows = [r for r in csv.DictReader(open(sys.argv[1], encoding="utf-8")) if r["status"] == "convertible"]
    work, outp = sys.argv[2], sys.argv[3]
    per = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    budget = float(sys.argv[5]) * 1e6 if len(sys.argv) > 5 else 480e6
    s3 = boto3.client("s3"); os.makedirs(OUT, exist_ok=True)
    size = {}
    for r in rows:
        if r["archive"] not in size:
            size[r["archive"]] = s3.head_object(Bucket="bim-proprietary-data", Key="Disk-2/" + r["archive"])["ContentLength"]
    pick = []
    for fam in sorted({r["family"] for r in rows}):
        cand = sorted((r for r in rows if r["family"] == fam and int(r["members"]) >= 100), key=lambda r: size[r["archive"]])
        seen = set()
        for r in cand:
            if r["archive"] in seen: continue
            seen.add(r["archive"]); pick.append(r)
            if len(seen) >= per: break
    spent = 0
    for r in pick:
        if spent + size[r["archive"]] > budget:
            print("budget: skipping", r["archive"]); continue
        spent += size[r["archive"]]
        dest = "\\\\?\\" + os.path.abspath(os.path.join(work, str(abs(hash(r["archive"])) % 10 ** 8)))
        shutil.rmtree(dest, ignore_errors=True); os.makedirs(dest, exist_ok=True)
        rec = dict(archive=r["archive"], job_root=r["job_root"], predicted=r["family"], archive_mb=round(size[r["archive"]] / 1e6, 1))
        try:
            job = extract(r["archive"], r["job_root"], dest)
            m = re.match(rb"\s*version\s+([0-9.]+)", open(os.path.join(job, "main", "jsetup"), "rb").read(64))
            rec["version"] = m.group(1).decode() if m else "?"
            rec["prediction_ok"] = FAM.get(rec["version"][:3]) == r["family"]
            name = re.sub(r"[^A-Za-z0-9_-]+", "_", r["job_root"].split("/")[-1]).strip("_")[:60]
            out = os.path.join(OUT, f"{name}_stage2.step")
            p = subprocess.run([sys.executable, "-u", CLI, job, "-o", out, "--stage", "2", "--verify"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=7200)
            open(os.path.splitext(out)[0] + ".log", "w").write(p.stdout)
            sm = re.search(r"solids: (\{.*?\})", p.stdout); vs = re.search(r"with solids: (\d+); BRep valid: (\d+)", p.stdout)
            rec["solids"] = sm.group(1) if sm else None
            rec["valid"] = f"{vs.group(2)}/{vs.group(1)}" if vs else None
            rec["error"] = None if vs else p.stdout[-300:]
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"[:300]
        shutil.rmtree(dest, ignore_errors=True)
        with open(outp, "a", encoding="utf-8") as f: f.write(json.dumps(rec) + "\n")
        print(json.dumps({k: rec.get(k) for k in ("predicted", "version", "prediction_ok", "valid", "archive_mb", "error")}), rec["archive"][-60:], flush=True)
    print(f"downloaded {spent / 1e6:.1f} MB")
