"""List the contents of every .7z/.zip under an S3 prefix without downloading them.

Reads only the archive index via ranged GETs (zip central directory / 7z header), then records
the SDS2 jobs (folders containing main/jsetup) and other model formats found inside.

usage: python probe_archives.py <listing.txt> <out.jsonl> [prefix] [threads]
Resumable: keys already present in out.jsonl are skipped.
"""
import sys, os, io, json, re, zipfile, collections, threading, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import boto3, botocore
import py7zr

BUCKET = "bim-proprietary-data"
BLOCK = 1 << 20
MODEL_EXT = {"ifc", "stp", "step", "db1", "tsd", "rvt", "dwg", "dxf", "nc1", "kss", "sdnf", "cis",
             "skp", "nwd", "nwc", "jft", "7z", "zip", "rar", "pdf"}

_s3 = threading.local()
def s3():
    if not hasattr(_s3, "c"):
        _s3.c = boto3.client("s3", config=botocore.config.Config(retries={"max_attempts": 8}))
    return _s3.c


class S3File(io.RawIOBase):
    """Seekable read-only view of an S3 object with a small block cache."""
    def __init__(self, key, size):
        self.key, self.size, self.pos, self.cache, self.fetched = key, size, 0, {}, 0
    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos
    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos
    def _block(self, i):
        if i not in self.cache:
            if len(self.cache) > 64:
                self.cache.clear()
            lo = i * BLOCK
            hi = min(self.size, lo + BLOCK) - 1
            r = s3().get_object(Bucket=BUCKET, Key=self.key, Range=f"bytes={lo}-{hi}")
            self.cache[i] = r["Body"].read()
            self.fetched += len(self.cache[i])
        return self.cache[i]
    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        n = max(0, min(n, self.size - self.pos))
        out = bytearray()
        while n > 0:
            b = self._block(self.pos // BLOCK)
            o = self.pos % BLOCK
            chunk = b[o:o + n]
            if not chunk:
                break
            out += chunk; self.pos += len(chunk); n -= len(chunk)
        return bytes(out)
    def readinto(self, b):
        d = self.read(len(b)); b[:len(d)] = d; return len(d)


def ext_of(name):
    base = name.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def summarise(names_sizes, read_member=None):
    jobs = {}
    fmt = collections.Counter()
    fmt_bytes = collections.Counter()
    db1_dirs = set()
    for name, size in names_sizes:
        n = name.replace("\\", "/")
        e = ext_of(n)
        if e in MODEL_EXT:
            fmt[e] += 1; fmt_bytes[e] += size or 0
        low = n.lower()
        if low.endswith("/main/jsetup") or low == "main/jsetup":
            root = n[: -len("main/jsetup")].rstrip("/")
            jobs[root] = {"jsetup": n}
        if e == "db1":
            db1_dirs.add(n.rsplit("/", 1)[0] if "/" in n else "")
    # per-job file counts / sizes, member counts
    for root in jobs:
        pre = (root + "/") if root else ""
        cnt = sz = mem = 0
        idx_sz = mtrl_sz = None
        for name, size in names_sizes:
            n = name.replace("\\", "/")
            if n.startswith(pre):
                cnt += 1; sz += size or 0
                rel = n[len(pre):].lower()
                if rel.startswith("mem/"):
                    mem += 1
                    if rel == "mem/mem_idx": idx_sz = size
                if rel == "main/job_mtrl": mtrl_sz = size
        # SDS2 version family from mem_idx slot size: (size - 256) % slot == 0
        fam = next((v for s, v in ((2494, "7.2xx"), (2944, "7.3xx"), (2976, "7.4xx")) if idx_sz and (idx_sz - 256) % s == 0), None)
        jobs[root].update(files=cnt, bytes=sz, mem_files=mem, mem_idx_size=idx_sz, job_mtrl_size=mtrl_sz, family=fam)
        if read_member:
            try:
                head = read_member(jobs[root]["jsetup"])
                m = re.match(rb"\s*version\s+([0-9.]+)", head or b"")
                if m:
                    jobs[root]["version"] = m.group(1).decode()
            except Exception as ex:
                jobs[root]["version_err"] = str(ex)[:100]
    return {"entries": len(names_sizes), "jobs": jobs, "formats": dict(fmt),
            "format_bytes": dict(fmt_bytes), "tekla_model_dirs": len(db1_dirs)}


def probe(key, size):
    print(f"START {size/1e9:.1f}GB {key}", file=sys.stderr, flush=True)
    f = S3File(key, size)
    e = ext_of(key)
    try:
        if e == "zip":
            z = zipfile.ZipFile(io.BufferedReader(f, buffer_size=BLOCK))
            infos = z.infolist()
            def rd(name):
                with z.open(name) as m:
                    return m.read(200)
            res = summarise([(i.filename, i.file_size) for i in infos], rd)
        elif e == "7z":
            with py7zr.SevenZipFile(io.BufferedReader(f, buffer_size=BLOCK), mode="r") as z:
                lst = z.list()
                res = summarise([(i.filename, i.uncompressed or 0) for i in lst])
                res["solid"] = bool(getattr(z, "solid", False)) if hasattr(z, "solid") else None
        else:
            return {"key": key, "size": size, "skipped": e}
        res.update(key=key, size=size, fetched=f.fetched)
        return res
    except Exception as ex:
        return {"key": key, "size": size, "error": f"{type(ex).__name__}: {str(ex)[:200]}", "fetched": f.fetched}


def main():
    listing, out = sys.argv[1], sys.argv[2]
    prefix = sys.argv[3] if len(sys.argv) > 3 else "Disk-2/"
    threads = int(sys.argv[4]) if len(sys.argv) > 4 else 16
    todo = []
    with open(listing, encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            p = line.rstrip("\n").split(None, 3)
            if len(p) == 4 and p[2].isdigit() and p[3].startswith(prefix) and ext_of(p[3]) in ("zip", "7z", "rar"):
                todo.append((p[3], int(p[2])))
    if os.environ.get("REPROBE_FROM"):
        # second pass: only archives that held SDS2 jobs in an earlier run without per-job version info
        need = set()
        for line in open(os.environ["REPROBE_FROM"], encoding="utf-8"):
            r = json.loads(line)
            if r.get("jobs") and any(j.get("family") is None and j.get("mem_idx_size") is None for j in r["jobs"].values()):
                need.add(r["key"])
        todo = [t for t in todo if t[0] in need]
    done = set()
    if os.path.exists(out):
        for line in open(out, encoding="utf-8"):
            try: done.add(json.loads(line)["key"])
            except Exception: pass
    todo = [t for t in todo if t[0] not in done]
    todo.sort(key=lambda t: t[1])  # small first
    print(f"{len(todo)} archives to probe ({len(done)} already done)", flush=True)
    lock = threading.Lock()
    n = 0
    with open(out, "a", encoding="utf-8") as fo, ThreadPoolExecutor(threads) as ex:
        futs = {ex.submit(probe, k, s): k for k, s in todo}
        for fu in as_completed(futs):
            r = fu.result()
            with lock:
                fo.write(json.dumps(r) + "\n"); fo.flush()
                n += 1
                if n % 50 == 0:
                    print(f"{n}/{len(todo)}", flush=True)
    print("done", flush=True)

if __name__ == "__main__":
    main()
