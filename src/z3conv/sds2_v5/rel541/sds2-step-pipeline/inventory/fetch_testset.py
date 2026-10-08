"""Fetch a decoding test set from Disk-2: for each (label, archive, [job_root, ...]) extract only main/ mem/ subm/
of those jobs into <dest>/<label>/<job_root>, delete the archive, and write <dest>/manifest.json.
usage: python fetch_testset.py <dest> <testset.json>
"""
import os, sys, json, re, zipfile, shutil
import boto3, py7zr

BUCKET = "bim-proprietary-data"
norm = lambda n: n.replace("\\", "/")


def _remote_zip(archive):
    """Zip on S3 opened through ranged GETs (only the central directory and the chosen members are fetched)."""
    import io
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from probe_archives import S3File
    size = boto3.client("s3").head_object(Bucket=BUCKET, Key="Disk-2/" + archive)["ContentLength"]
    f = S3File("Disk-2/" + archive, size)
    return zipfile.ZipFile(io.BufferedReader(f, 1 << 20)), f


def fetch(archive, job_roots, dest, plan=False):
    pref = tuple(f"{norm(j)}/{d}/" for j in job_roots for d in ("main", "mem", "subm"))
    if archive.lower().endswith(".zip"):
        z, f = _remote_zip(archive)
        infos = [i for i in z.infolist() if norm(i.filename).startswith(pref) and not i.is_dir()]
        need = sum(i.compress_size for i in infos)
        if plan:
            return need / 1e6
        for i in infos:
            z.extract(i, dest)
        return f.fetched / 1e6
    if plan:
        return boto3.client("s3").head_object(Bucket=BUCKET, Key="Disk-2/" + archive)["ContentLength"] / 1e6
    local = os.path.join(dest, "_a" + os.path.splitext(archive)[1])
    boto3.client("s3").download_file(BUCKET, "Disk-2/" + archive, local)
    mb = os.path.getsize(local) / 1e6
    if True:
        with py7zr.SevenZipFile(local, "r") as z:
            names = [n for n in z.getnames() if norm(n).startswith(pref)]
        with py7zr.SevenZipFile(local, "r") as z:
            z.extract(path=dest, targets=names)
    os.remove(local)
    return mb


def describe(job):
    v = ""
    try:
        m = re.match(rb"\s*version\s+([0-9.]+)", open(os.path.join(job, "main", "jsetup"), "rb").read(64))
        v = m.group(1).decode() if m else ""
    except OSError:
        pass
    size = lambda *p: os.path.getsize(os.path.join(job, *p)) if os.path.exists(os.path.join(job, *p)) else None
    count = lambda d: sum(n.isdigit() for n in os.listdir(os.path.join(job, d))) if os.path.isdir(os.path.join(job, d)) else 0
    return dict(version=v, members=count("mem"), pieces=count("subm"), job_mtrl=size("main", "job_mtrl"),
                mem_idx=size("mem", "mem_idx"), subm_idx=size("subm", "subm_idx"))


if __name__ == "__main__":
    dest, items = sys.argv[1], json.load(open(sys.argv[2]))
    if "--plan" in sys.argv:                      # print bytes to fetch per item (zip: compressed main/mem/subm only)
        tot = 0.0
        for label, archive, roots in items:
            mb = fetch(archive, roots, dest, plan=True); tot += mb
            print(f"{label:28s} {mb:8.1f} MB  {archive.split('/')[-1]}", flush=True)
        print(f"total {tot:.1f} MB"); sys.exit(0)
    os.makedirs(dest, exist_ok=True)
    man_p = os.path.join(dest, "manifest.json")
    man = json.load(open(man_p)) if os.path.exists(man_p) else {}
    total = 0.0
    for label, archive, roots in items:
        d = "\\\\?\\" + os.path.abspath(os.path.join(dest, label))
        if all(os.path.exists(os.path.join(d, *norm(r).split("/"), "mem", "mem_idx")) for r in roots):
            print("have", label); continue
        os.makedirs(d, exist_ok=True)
        mb = fetch(archive, roots, d); total += mb
        for r in roots:
            job = os.path.join(d, *norm(r).split("/"))
            man[f"{label}/{r}"] = dict(archive=archive, archive_mb=round(mb, 1), path=job[4:], **describe(job))
            print(f"{label}/{r}: {man[f'{label}/{r}']}", flush=True)
        json.dump(man, open(man_p, "w"), indent=1)
    print(f"downloaded {total:.1f} MB")
