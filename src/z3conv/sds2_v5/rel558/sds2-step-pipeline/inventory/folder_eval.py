"""Preflight every SDS2 job in every archive under one Disk-2 folder (downloaded once each, deleted after).

usage: python folder_eval.py <disk2_folder> <workdir> <out.jsonl> [threads]
An archive counts as convertible at the best stage any of its jobs reaches.
"""
import os, sys, json, csv, shutil, subprocess, zipfile, collections, threading
from concurrent.futures import ThreadPoolExecutor
import boto3, py7zr

INV = os.path.dirname(os.path.abspath(__file__))
DECODE = os.path.join(os.path.dirname(INV), "decode")
BUCKET = "bim-proprietary-data"
lock = threading.Lock()
norm = lambda n: n.replace("\\", "/")


def archives_in(folder):
    recs = {}
    for line in open(os.path.join(INV, "disk2_archives.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r["key"] not in recs or "error" in recs[r["key"]]:
            recs[r["key"]] = r
    pre = "Disk-2/" + folder.rstrip("/") + "/"
    return {k[7:]: r for k, r in recs.items() if k.startswith(pre)}


def run(archive, rec, work, outp):
    jobs = sorted((rec.get("jobs") or {}).keys())
    base = {"archive": archive, "archive_mb": round(rec.get("size", 0) / 1e6, 1), "n_jobs": len(jobs)}
    if not jobs:
        with lock, open(outp, "a", encoding="utf-8") as f:
            f.write(json.dumps({**base, "best": "no SDS2 job"}) + "\n")
        return
    dest = "\\\\?\\" + os.path.abspath(os.path.join(work, str(abs(hash(archive)) % 10 ** 10)))
    shutil.rmtree(dest, ignore_errors=True); os.makedirs(dest, exist_ok=True)
    results = []
    try:
        local = os.path.join(dest, "a" + os.path.splitext(archive)[1])
        boto3.client("s3").download_file(BUCKET, "Disk-2/" + archive, local)
        pref = tuple(f"{norm(j)}/{d}/" for j in jobs for d in ("main", "mem", "subm"))
        if local.lower().endswith(".zip"):
            with zipfile.ZipFile(local) as z:
                for i in z.infolist():
                    if norm(i.filename).startswith(pref) and not i.is_dir(): z.extract(i, dest)
        else:
            with py7zr.SevenZipFile(local, "r") as z:
                names = [n for n in z.getnames() if norm(n).startswith(pref)]
            with py7zr.SevenZipFile(local, "r") as z:
                z.extract(path=dest, targets=names)
        os.remove(local)
        for j in jobs:
            p = subprocess.run([sys.executable, os.path.join(DECODE, "preflight.py"), os.path.join(dest, *norm(j).split("/")), "120"],
                               capture_output=True, text=True, timeout=3600)
            last = [l for l in p.stdout.splitlines() if l.startswith("{")]
            r = json.loads(last[-1]) if last else {"verdict": "no", "error": p.stderr[-200:]}
            r["job_root"] = j; r.pop("job", None); results.append(r)
    except Exception as e:
        results.append({"verdict": "error", "error": f"{type(e).__name__}: {e}"[:300]})
    shutil.rmtree(dest, ignore_errors=True)
    rank = {"stage2": 3, "stage1": 2, "no": 1, "error": 0}
    best = max((r["verdict"] for r in results), key=lambda v: rank.get(v, 0))
    with lock, open(outp, "a", encoding="utf-8") as f:
        f.write(json.dumps({**base, "best": best, "jobs": results}) + "\n")
    print(best, len(jobs), "jobs", archive[-70:], flush=True)


if __name__ == "__main__":
    folder, work, outp = sys.argv[1], sys.argv[2], sys.argv[3]
    threads = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    A = archives_in(folder)
    done = {json.loads(l)["archive"] for l in open(outp, encoding="utf-8")} if os.path.exists(outp) else set()
    print(len(A), "archives,", round(sum(r.get("size", 0) for r in A.values()) / 1e6), "MB", flush=True)
    os.makedirs(work, exist_ok=True)
    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(lambda kv: run(kv[0], kv[1], work, outp), [kv for kv in sorted(A.items()) if kv[0] not in done]))
