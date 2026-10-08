"""Empirical convertibility of Disk-2 archives: for each SDS2 version, pull a few real archives from S3, extract only the
job's main/ mem/ subm/ folders, run decode/preflight.py on each job, record the verdict.

usage: python sample_convertibility.py <workdir> <out.jsonl> [per_version] [threads] [items.json]
Resumable: archives already in out.jsonl are skipped.
"""
import os, io, sys, json, csv, shutil, subprocess, zipfile, collections, threading
from concurrent.futures import ThreadPoolExecutor
import boto3
import py7zr

INV = os.path.dirname(os.path.abspath(__file__))
DECODE = os.path.join(os.path.dirname(INV), "decode")
BUCKET = "bim-proprietary-data"
PY = sys.executable
lock = threading.Lock()


def pick(per_version):
    recs = {}
    for line in open(os.path.join(INV, "disk2_archives.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r["key"] not in recs or "error" in recs[r["key"]]:
            recs[r["key"]] = r
    size = {k[len("Disk-2/"):]: r.get("size", 0) for k, r in recs.items()}
    rows = [r for r in csv.DictReader(open(os.path.join(INV, "disk2_models.csv"), encoding="utf-8"))
            if r["source"] == "archive" and r["junk"] != "True" and int(r["members"]) >= 100
            and size.get(r["archive"], 0) < 3e9 and r["archive"].lower().endswith((".zip", ".7z"))]
    byv = collections.defaultdict(list)
    for r in rows:
        byv[r["version"] or "unknown"].append(r)
    out = []
    for v, rs in byv.items():
        rs.sort(key=lambda r: size[r["archive"]])
        seen = set()
        n = per_version * (3 if v == "unknown" else 1)
        for r in rs:
            if r["archive"] in seen: continue
            seen.add(r["archive"]); out.append((v, r["archive"], r["job_root"], size[r["archive"]]))
            if len(seen) >= n: break
    return out


def extract(archive, job_root, dest):
    """Download the archive and extract <job_root>/{main,mem,subm}/ only. Returns the job folder path."""
    s3 = boto3.client("s3")
    pref = tuple(f"{job_root}/{d}/".replace("\\", "/") for d in ("main", "mem", "subm"))
    norm = lambda n: n.replace("\\", "/")
    size = s3.head_object(Bucket=BUCKET, Key="Disk-2/" + archive)["ContentLength"]
    if archive.lower().endswith(".zip") and size > 1e9:
        # big zip: read the central directory and only the job's members with ranged GETs
        from probe_archives import S3File
        with zipfile.ZipFile(io.BufferedReader(S3File("Disk-2/" + archive, size), 1 << 20)) as z:
            for i in z.infolist():
                if norm(i.filename).startswith(pref) and not i.is_dir():
                    z.extract(i, dest)
        return os.path.join(dest, *job_root.replace("\\", "/").split("/"))
    local = os.path.join(dest, "a" + os.path.splitext(archive)[1])
    s3.download_file(BUCKET, "Disk-2/" + archive, local)
    if local.endswith(".zip"):
        with zipfile.ZipFile(local) as z:
            for i in z.infolist():
                if norm(i.filename).startswith(pref) and not i.is_dir():
                    z.extract(i, dest)
    else:
        with py7zr.SevenZipFile(local, "r") as z:
            names = [n for n in z.getnames() if norm(n).startswith(pref)]
        with py7zr.SevenZipFile(local, "r") as z:
            z.extract(path=dest, targets=names)
    os.remove(local)
    return os.path.join(dest, *job_root.replace("\\", "/").split("/"))


def run(item, work, outp, done):
    v, archive, job_root, sz = item
    if archive in done: return
    dest = os.path.join(work, str(abs(hash(archive)) % 10 ** 10))
    if os.name == "nt":                            # nested job folders exceed MAX_PATH: use extended-length paths
        dest = "\\\\?\\" + os.path.abspath(dest)
    rec = {"version_csv": v, "archive": archive, "job_root": job_root, "archive_gb": round(sz / 1e9, 3)}
    try:
        shutil.rmtree(dest, ignore_errors=True); os.makedirs(dest, exist_ok=True)
        job = extract(archive, job_root, dest)
        p = subprocess.run([PY, os.path.join(DECODE, "preflight.py"), job, "120"], capture_output=True, text=True, timeout=3600)
        last = [l for l in p.stdout.splitlines() if l.startswith("{")]
        rec.update(json.loads(last[-1]) if last else {"verdict": "no", "error": p.stderr[-300:]})
    except Exception as e:
        rec.update(verdict="error", error=f"{type(e).__name__}: {e}"[:300])
    shutil.rmtree(dest, ignore_errors=True)
    with lock:
        with open(outp, "a", encoding="utf-8") as f: f.write(json.dumps(rec) + "\n")
        print(v, rec.get("verdict"), archive[-70:], flush=True)


if __name__ == "__main__":
    work, outp = sys.argv[1], sys.argv[2]
    per = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    threads = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    done = set()
    if os.path.exists(outp):
        done = {json.loads(l)["archive"] for l in open(outp, encoding="utf-8")}
    # optional 5th arg: JSON file with an explicit list of [version, archive, job_root, size] items
    items = json.load(open(sys.argv[5])) if len(sys.argv) > 5 else pick(per)
    print(len(items), "archives sampled", flush=True)
    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(lambda it: run(it, work, outp, done), items))
