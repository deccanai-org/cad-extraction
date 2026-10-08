"""Re-read the .7z listings (headers only) of the unknown-version archives and record, per SDS2 job, the sizes the
fingerprint needs: main/job_mtrl, mem/mem_idx, subm/subm_idx, and the member files present. Cheapest archives first
(by the bytes the original index needed), stopping before a download budget.
usage: python list_unknown.py <out.jsonl> [budget_mb]
"""
import os, sys, json, csv, re
import boto3, py7zr
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe_archives import S3File

INV = os.path.dirname(os.path.abspath(__file__))
BUCKET = "bim-proprietary-data"


def unknown_archives():
    recs = {}
    for line in open(os.path.join(INV, "disk2_archives.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r["key"] not in recs or "error" in recs[r["key"]]:
            recs[r["key"]] = r
    rows = [r for r in csv.DictReader(open(os.path.join(INV, "disk2_models.csv"), encoding="utf-8")) if r["source"] == "archive"]
    A = {}
    for r in rows: A.setdefault(r["archive"], []).append(r)
    ua = [a for a, js in A.items() if all(not j["version"] for j in js)]
    return sorted(((a, recs["Disk-2/" + a]) for a in ua), key=lambda t: t[1].get("fetched", 0))


def jobs_from_listing(entries):
    """entries: [(name, size)] -> {job_root: {job_mtrl, mem_idx, subm_idx, max_mem, n_mem}}"""
    norm = lambda n: n.replace("\\", "/")
    roots = {norm(n)[:-len("/main/jsetup")] for n, s in entries if norm(n).lower().endswith("/main/jsetup")}
    out = {r: dict(job_mtrl=None, mem_idx=None, subm_idx=None, max_mem=0, n_mem=0) for r in roots}
    for n, s in entries:
        n = norm(n)
        for r in roots:
            if not n.startswith(r + "/"): continue
            rest = n[len(r) + 1:].lower()
            if rest == "main/job_mtrl": out[r]["job_mtrl"] = s
            elif rest == "mem/mem_idx": out[r]["mem_idx"] = s
            elif rest == "subm/subm_idx": out[r]["subm_idx"] = s
            elif re.fullmatch(r"mem/\d+", rest):
                out[r]["n_mem"] += 1; out[r]["max_mem"] = max(out[r]["max_mem"], int(rest[4:]))
    return out


if __name__ == "__main__":
    outp = sys.argv[1]; budget = float(sys.argv[2]) * 1e6 if len(sys.argv) > 2 else 480e6
    done = {json.loads(l)["archive"] for l in open(outp, encoding="utf-8")} if os.path.exists(outp) else set()
    spent = sum(json.loads(l).get("fetched", 0) for l in open(outp, encoding="utf-8")) if os.path.exists(outp) else 0
    s3 = boto3.client("s3")
    for a, rec in unknown_archives():
        if a in done: continue
        est = rec.get("fetched", 0)
        if spent + est > budget:
            print(f"budget reached before {a} (est {est / 1e6:.1f} MB)"); break
        size = s3.head_object(Bucket=BUCKET, Key="Disk-2/" + a)["ContentLength"]
        f = S3File("Disk-2/" + a, size)
        row = dict(archive=a, size=size)
        try:
            with py7zr.SevenZipFile(f, "r") as z:
                entries = [(i.filename, i.uncompressed) for i in z.list()]
            row["jobs"] = jobs_from_listing(entries)
        except Exception as e:
            row["error"] = f"{type(e).__name__}: {e}"[:200]
        row["fetched"] = f.fetched; spent += f.fetched
        with open(outp, "a", encoding="utf-8") as fo: fo.write(json.dumps(row) + "\n")
        print(f"{spent / 1e6:7.1f} MB  {len(row.get('jobs', {}))} jobs  {a[-70:]}", flush=True)
    print(f"total fetched {spent / 1e6:.1f} MB")
