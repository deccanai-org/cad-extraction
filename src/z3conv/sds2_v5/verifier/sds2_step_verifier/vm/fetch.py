"""Fetch one SDS2 job (plus nearby ground truth) out of an S3 archive via a presigned URL.

zip : random access over HTTP Range requests - only the job folder's bytes are transferred, even for 68 GB zips
7z  : solid archives need the whole file; it is downloaded once (shared by jobs from the same archive) and only
      the job folder + ground-truth files are extracted
Ground truth = .ifc/.kss/.nc1 files under the job folder's parent directory inside the archive (the project
folder). If the job sits at the archive root of a multi-job archive, no ground truth is taken (it could belong to
another job).
"""
import io, os, re, sys, time, zipfile, shutil, threading, subprocess, urllib.request

BLOCK = 8 << 20
PREFETCH = 6          # parallel ranged GETs per job
GT_EXT = (".ifc", ".kss", ".nc1")


class HTTPFile(io.RawIOBase):
    def __init__(self, url, size=None):
        self.url, self.pos, self.cache, self.fetched = url, 0, {}, 0
        if size is None:
            req = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                size = int(r.headers["Content-Range"].split("/")[-1])
        self.size = size
    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos
    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos
    def _get(self, i):
        lo = i * BLOCK; hi = min(self.size, lo + BLOCK) - 1
        for attempt in range(6):
            try:
                req = urllib.request.Request(self.url, headers={"Range": f"bytes={lo}-{hi}"})
                with urllib.request.urlopen(req, timeout=300) as r:
                    return r.read()
            except Exception:
                if attempt == 5: raise
                time.sleep(2 ** attempt)

    def _block(self, i):
        """Sequential reads (zip member extraction) trigger a parallel prefetch of the next blocks, so one job pulls
        PREFETCH ranged GETs at once instead of a single stream."""
        if not hasattr(self, "_pool"):
            from concurrent.futures import ThreadPoolExecutor
            self._pool = ThreadPoolExecutor(PREFETCH); self._pending = {}
        nblocks = (self.size + BLOCK - 1) // BLOCK
        for j in range(i, min(nblocks, i + PREFETCH)):
            if j not in self.cache and j not in self._pending:
                self._pending[j] = self._pool.submit(self._get, j)
        if i not in self.cache:
            fut = self._pending.pop(i, None)
            self.cache[i] = fut.result() if fut else self._get(i)
            self.fetched += len(self.cache[i])
        while len(self.cache) > 4 * PREFETCH:
            self.cache.pop(next(iter(self.cache)))
        for j in [j for j in self._pending if j < i]:          # stale prefetches after a backwards seek
            self._pending.pop(j).cancel()
        return self.cache[i]
    def read(self, n=-1):
        if n is None or n < 0: n = self.size - self.pos
        n = max(0, min(n, self.size - self.pos)); out = bytearray()
        while n > 0:
            b = self._block(self.pos // BLOCK); o = self.pos % BLOCK; c = b[o:o + n]
            if not c: break
            out += c; self.pos += len(c); n -= len(c)
        return bytes(out)
    def readinto(self, b):
        d = self.read(len(b)); b[:len(d)] = d; return len(d)


def _wanted(names, job_root, allow_gt):
    if not job_root.strip("/"):                 # job sits at the archive root (main/, mem/ at top level)
        return [n for n in names if not n.lower().endswith(GT_EXT)], []
    jr = job_root.rstrip("/") + "/"
    parent = jr.rsplit("/", 2)[0] + "/" if jr.count("/") >= 2 else ""
    want = [n for n in names if n.replace("\\", "/").startswith(jr)]
    gt = []
    if allow_gt and parent:
        gt = [n for n in names if n.replace("\\", "/").startswith(parent) and n.lower().endswith(GT_EXT)
              and not n.replace("\\", "/").startswith(jr)]
    return want, gt


_dl_lock = threading.Lock()


def _parallel_download(url, path, chunk=32 << 20, threads=8):
    """Whole-object download as parallel ranged GETs written in place (one S3 stream tops out well below the NIC)."""
    from concurrent.futures import ThreadPoolExecutor
    size = HTTPFile(url).size
    with open(path, "wb") as f:
        f.truncate(size)
    def part(lo):
        hi = min(size, lo + chunk) - 1
        for attempt in range(6):
            try:
                req = urllib.request.Request(url, headers={"Range": f"bytes={lo}-{hi}"})
                with urllib.request.urlopen(req, timeout=600) as r:
                    data = r.read()
                with open(path, "r+b") as f:
                    f.seek(lo); f.write(data)
                return len(data)
            except Exception:
                if attempt == 5: raise
                time.sleep(2 ** attempt)
    with ThreadPoolExecutor(threads) as ex:
        got = sum(ex.map(part, range(0, size, chunk)))
    if got != size:
        raise IOError(f"download incomplete {got}/{size}")


def fetch(url, archive, job_root, dest, cache_dir, jobs_in_archive=1):
    os.makedirs(dest, exist_ok=True)
    t0 = time.time(); ext = archive.lower().rsplit(".", 1)[-1]
    allow_gt = True
    if "/" not in job_root.strip("/") and int(jobs_in_archive or 1) > 1:
        allow_gt = False
    if ext == "zip":
        f = HTTPFile(url)
        z = zipfile.ZipFile(io.BufferedReader(f, buffer_size=BLOCK))
        names = z.namelist()
        want, gt = _wanted(names, job_root, allow_gt)
        for n in want + gt:
            if n.endswith("/"): continue
            z.extract(n, dest)
        got = f.fetched
    else:
        import py7zr
        local = os.path.join(cache_dir, re.sub(r"[^A-Za-z0-9._-]+", "_", archive))
        with _dl_lock:
            pass
        lock = local + ".lock"
        while os.path.exists(lock) and time.time() - os.path.getmtime(lock) < 7200:
            time.sleep(5)
        if not os.path.exists(local):
            open(lock, "w").close()
            try:
                tmp = local + ".part"
                _parallel_download(url, tmp)
                os.replace(tmp, local)
            finally:
                os.remove(lock)
        got = os.path.getsize(local)
        with py7zr.SevenZipFile(local, "r") as z:
            infos = z.list()
        names = [i.filename for i in infos]
        want, gt = _wanted(names, job_root, allow_gt)
        exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "7zr.exe")
        if os.path.exists(exe):
            # native 7-Zip: 20-50x faster than py7zr. Exact names via a UTF-8 list file, wildcards disabled (-spd)
            dirs = {i.filename for i in infos if i.is_directory}
            lst = os.path.join(dest, "_extract_list.txt")
            with open(lst, "w", encoding="utf-8") as fl:
                for n in want + gt:
                    if n not in dirs: fl.write(n.replace("/", "\\") + "\n")
            p = subprocess.run([exe, "x", local, f"-o{dest}", "-y", "-spd", "-scsUTF-8", f"@{lst}"],
                               capture_output=True, text=True, errors="replace")
            os.remove(lst)
            if p.returncode not in (0, 1):
                raise RuntimeError(f"7zr failed rc={p.returncode}: {p.stderr[-300:] or p.stdout[-300:]}")
        else:
            with py7zr.SevenZipFile(local, "r") as z:
                z.extract(path=dest, targets=want + gt)
    jobdir = os.path.join(dest, *job_root.strip("/").split("/"))
    gtdir = os.path.dirname(jobdir) if (allow_gt and gt) else None
    return dict(jobdir=jobdir, gt_dir=gtdir, gt_files=len(gt), files=len(want), bytes_fetched=got, seconds=round(time.time() - t0, 1))


if __name__ == "__main__":
    print(fetch(*sys.argv[1:5], cache_dir=sys.argv[5] if len(sys.argv) > 5 else "."))
