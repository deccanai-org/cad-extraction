"""Convert SDS2 jobs to STEP at scale, in parallel, resumably. Works for every supported SDS2 version (7.0xx - 8.0xx);
the layout is detected per job by decode/sds2_to_step.py.

Sources
  --s3                     archives listed in inventory/disk2_models.csv (s3://bim-proprietary-data/Disk-2/...);
                           only each job's main/ mem/ subm/ folders are extracted (big zips via ranged reads).
  --local ROOT             job folders (main/job_mtrl + mem/mem_idx) and .zip/.7z archives found under ROOT.

Filters (s3):  --versions 7.3,7.6,8.0  --match REGEX  --include-junk  --min-members N  --limit N  --items items.json
Output:        OUT/<version>/<name>/<name>_stage2.step (+ _pieces.csv, _preview.png, .log), OUT/results.jsonl,
               OUT/summary.csv, OUT/summary.md. Re-running skips jobs already in results.jsonl (--retry-failed redoes
               failures).
Parallelism:   --workers N archives in flight; --convert-jobs N conversions at once (each conversion is one
               single-threaded process); a conversion starts only when --min-free-gb RAM and --min-disk-gb disk are
               free. Defaults are sized from this machine's cores and memory.
Examples:
  python batch/run_batch.py --s3 --plan                                   # what would run, no S3 access
  python batch/run_batch.py --s3 --versions 7.0,7.1 --out D:/step_out --convert-jobs 6
  python batch/run_batch.py --local "D:/sds2_jobs" --out D:/step_out --stage both --no-verify
"""
import argparse, collections, csv, hashlib, io, json, os, re, shutil, subprocess, sys, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DECODE = os.path.join(ROOT, "decode")
INV = os.path.join(ROOT, "inventory")
BUCKET, PREFIX = "bim-proprietary-data", "Disk-2/"
lock = threading.Lock()


# ---------------------------------------------------------------------------------------------------------- system
def free_ram_gb():
    try:
        if os.name == "nt":
            import ctypes
            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                            ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
            m = MS(); m.l = ctypes.sizeof(MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.avail / 2 ** 30
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable"):
                return int(line.split()[1]) / 2 ** 20
    except Exception:
        pass
    return 1e9


def lp(path):
    """Extended-length path on Windows (job folders nest past MAX_PATH)."""
    p = os.path.abspath(path)
    return "\\\\?\\" + p if os.name == "nt" and not p.startswith("\\\\?\\") else p


def safe(s, n=60):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_")[:n] or "job"


def is_job(d):
    return os.path.exists(os.path.join(d, "main", "job_mtrl")) and os.path.exists(os.path.join(d, "mem", "mem_idx"))


def read_version(job):
    try:
        m = re.match(rb"\s*version\s+([0-9.]+)", open(os.path.join(job, "main", "jsetup"), "rb").read(64))
        return m.group(1).decode() if m else "unknown"
    except OSError:
        return "unknown"


# ---------------------------------------------------------------------------------------------------------- items
def s3_items(a):
    rows = [r for r in csv.DictReader(open(os.path.join(INV, "disk2_models.csv"), encoding="utf-8")) if r["source"] == "archive"]
    if not a.include_junk: rows = [r for r in rows if r["junk"] != "True"]
    rows = [r for r in rows if int(r["members"] or 0) >= a.min_members]
    if a.versions:
        vs = [v.strip() for x in a.versions for v in x.split(",") if v.strip()]
        rows = [r for r in rows if any((r["version"] or "unknown").startswith(v) for v in vs)]
    if a.match: rows = [r for r in rows if re.search(a.match, r["archive"] + "/" + r["job_root"], re.I)]
    if a.items:
        want = {(x[1], x[2]) for x in json.load(open(a.items))}
        rows = [r for r in rows if (r["archive"], r["job_root"]) in want]
    size = {}
    p = os.path.join(INV, "disk2_archives.jsonl")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            if "error" not in r or r["key"] not in size: size[r["key"][len(PREFIX):]] = r.get("size", 0)
    by = collections.OrderedDict()
    for r in sorted(rows, key=lambda r: size.get(r["archive"], 0)):          # small archives first
        by.setdefault(r["archive"], []).append((r["job_root"], r["version"] or "unknown"))
    items = [dict(kind="s3", archive=k, jobs=v, size=size.get(k, 0)) for k, v in by.items()]
    return items[: a.limit] if a.limit else items


def local_items(a):
    items = []; top = lp(a.local)
    for d, subs, files in os.walk(top):
        if is_job(d):
            items.append(dict(kind="dir", archive=d, jobs=[("", "unknown")], size=0)); subs[:] = []; continue
        for f in files:
            if f.lower().endswith((".zip", ".7z")):
                p = os.path.join(d, f); items.append(dict(kind="file", archive=p, jobs=None, size=os.path.getsize(p)))
    if a.match: items = [i for i in items if re.search(a.match, i["archive"], re.I)]
    return items[: a.limit] if a.limit else items


# ---------------------------------------------------------------------------------------------------------- extract
def _s3file(key, size):
    sys.path.insert(0, INV)
    from probe_archives import S3File
    return io.BufferedReader(S3File(key, size), 1 << 22)


def seven_zip_cli():
    """Path of a 7-Zip command-line binary (7zz from the '7zip' package, 7z / 7za from p7zip, or 7-Zip on Windows)."""
    for c in ("7zz", "7z", "7za"):
        p = shutil.which(c)
        if p: return p
    for p in (r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if os.path.exists(p): return p
    return None


def _free_gb(path):
    try: return shutil.disk_usage(path).free / 1e9
    except OSError: return 0.0


def _download(it, dest):
    import boto3
    local = os.path.join(dest, "archive" + os.path.splitext(it["archive"])[1])
    boto3.client("s3").download_file(BUCKET, PREFIX + it["archive"], local)
    return local


def _open_archive(it, dest, stream_gb, use_cli=True):
    """-> ("zip", ZipFile) | ("7z", local path or S3 file object). S3 zips > 1 GB are read in place with ranged
    GETs. A 7z is downloaded (and later opened with the 7-Zip CLI when present) unless it is larger than stream_gb
    and the scratch disk can't take it; then py7zr decompresses it straight from S3 (largest Disk-2 7z: 113 GB)."""
    if it["kind"] == "file":
        return ("zip", zipfile.ZipFile(it["archive"])) if it["archive"].lower().endswith(".zip") else ("7z", it["archive"])
    import boto3
    s3 = boto3.client("s3"); key = PREFIX + it["archive"]
    size = s3.head_object(Bucket=BUCKET, Key=key)["ContentLength"]
    it["size"] = size
    if it["archive"].lower().endswith(".zip") and size > 1e9:
        return "zip", zipfile.ZipFile(_s3file(key, size))
    if it["archive"].lower().endswith(".7z") and size > stream_gb * 1e9:
        room = _free_gb(dest) - size / 1e9 - 20                     # keep 20 GB for extracted jobs / outputs
        if not (use_cli and seven_zip_cli() and room > 0):
            return "7z", _s3file(key, size)
    local = _download(it, dest)
    return ("zip", zipfile.ZipFile(local)) if local.lower().endswith(".zip") else ("7z", local)


def _cli_list(exe, arc):
    p = subprocess.run([exe, "l", "-slt", "-ba", "-sccUTF-8", arc], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"7z list failed: {(p.stderr or p.stdout)[-300:]}")
    names, cur = [], {}
    for line in p.stdout.splitlines() + [""]:
        if not line.strip():
            if cur.get("Path") and cur.get("Folder", "-") != "+": names.append(cur["Path"])
            cur = {}; continue
        k, _, v = line.partition(" = ")
        cur[k] = v
    return names


def _cli_extract(exe, arc, members, tmp):
    os.makedirs(tmp, exist_ok=True)
    lst = os.path.join(tmp, "_members.txt")
    with open(lst, "w", encoding="utf-8") as f: f.write("\n".join(members) + "\n")
    p = subprocess.run([exe, "x", "-y", "-bso0", "-bsp0", "-scsUTF-8", f"-o{tmp}", f"-i@{lst}", arc],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    os.remove(lst)
    if p.returncode not in (0, 1):                           # 1 = warnings (e.g. a skipped file)
        raise RuntimeError(f"7z extract failed (rc {p.returncode}): {(p.stderr or p.stdout)[-300:]}")


CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}


def _target(dest, root, rel):
    """Local path for archive member <root>/<rel>: '/' separators whatever the archive used, and the SDS2 folder /
    index names in lower case (Linux is case-sensitive; archives made on Windows may say MAIN/ or Mem_Idx)."""
    parts = [p.lower() if p.lower() in CANON else p for p in rel.split("/") if p]
    return os.path.join(dest, *[p for p in root.split("/") if p], *parts)


def extract(it, dest, stream_gb=20, use_cli=True):
    """Extract <job_root>/{main,mem,subm}/ of every job in the archive (job roots from the listing, or found by
    */main/jsetup, case-insensitively). 7z: the 7-Zip CLI when available (all codecs, faster), else py7zr; a py7zr
    failure is retried with the CLI (downloading a streamed archive first if the disk allows).
    Returns [(job_root, local job folder)]."""
    kind, h = _open_archive(it, dest, stream_gb, use_cli)
    exe = seven_zip_cli() if use_cli else None
    if kind == "7z":
        if exe and isinstance(h, str):
            return _extract_members(it, dest, "7zcli", (exe, h))
        try:
            return _extract_members(it, dest, "7z", h)
        except Exception as e:
            if not exe or isinstance(e, (MemoryError, KeyboardInterrupt)): raise
            if not isinstance(h, str):                        # was streamed: needs a local copy for the CLI
                if _free_gb(dest) - (it.get("size") or 0) / 1e9 - 20 <= 0:
                    raise RuntimeError(f"archive unreadable with py7zr ({type(e).__name__}: {e}) and no disk for the 7-Zip CLI")
                h = _download(it, dest)
            shutil.rmtree(os.path.join(dest, "_7z"), ignore_errors=True)
            return _extract_members(it, dest, "7zcli", (exe, h))
    return _extract_members(it, dest, kind, h)


def _extract_members(it, dest, kind, h):
    norm = lambda n: n.replace("\\", "/")
    import py7zr
    if kind == "zip":
        names = h.namelist()
    elif kind == "7zcli":
        names = _cli_list(*h)
    else:
        with py7zr.SevenZipFile(h, "r") as z: names = z.getnames()
        if hasattr(h, "seek"): h.seek(0)
    low = {n: norm(n).lower() for n in names}
    roots = [norm(j) for j, _ in it["jobs"]] if it["jobs"] else \
        sorted({norm(n)[: -len("/main/jsetup")] for n in names if low[n].endswith("/main/jsetup")})
    want = {}                                                   # archive member -> local path
    for r in roots:
        rl = r.lower().rstrip("/")
        prefix = f"{rl}/" if rl else ""
        for n in names:
            L = low[n]
            if L.startswith(tuple(f"{prefix}{d}/" for d in ("main", "mem", "subm"))) and not L.endswith("/"):
                want[n] = _target(dest, r.rstrip("/"), norm(n)[len(prefix):])
    if kind == "zip":
        for n, out in want.items():                             # written by hand: zipfile would keep '\' in names
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with h.open(n) as src, open(out, "wb") as dst: shutil.copyfileobj(src, dst, 1 << 20)
        h.close()
    else:
        tmp = os.path.join(dest, "_7z")
        if kind == "7zcli":
            _cli_extract(h[0], h[1], list(want), tmp)
        else:
            with py7zr.SevenZipFile(h, "r") as z: z.extract(path=tmp, targets=list(want))
        for n, out in want.items():
            src = os.path.join(tmp, *norm(n).split("/"))
            if os.path.exists(src):
                os.makedirs(os.path.dirname(out), exist_ok=True); shutil.move(src, out)
        shutil.rmtree(tmp, ignore_errors=True)
    for f in os.listdir(dest):
        if f.startswith("archive."): os.remove(os.path.join(dest, f))
    return [(r, os.path.join(dest, *[p for p in r.rstrip("/").split("/") if p])) for r in roots]


# ---------------------------------------------------------------------------------------------------------- convert
def parse_log(txt):
    g = lambda pat, d=None, f=str: (lambda m: f(m.group(1)) if m else d)(re.search(pat, txt))
    return dict(version=g(r"SDS2 version (\S+)"), exact=g(r"'exact': (\d+)", 0, int), plate=g(r"'plate': (\d+)", 0, int),
                exact_brep=g(r"'exact_brep': (\d+)", 0, int),
                profile_fallback=g(r"'profile_fallback': (\d+)", 0, int),
                plate_fallback=g(r"'plate_fallback': (\d+)", 0, int),
                special_primitive=g(r"'special_primitive': (\d+)", 0, int),
                bolts_sds2=g(r"'bolts_sds2': (\d+)", 0, int), bolts_nominal=g(r"'bolts_nominal': (\d+)", 0, int),
                rolled=g(r"'rolled': (\d+)", 0, int), fastener=g(r"'fastener': (\d+)", 0, int),
                bolts=g(r"'bolts': (\d+)", 0, int), skipped=g(r"'skipped': (\d+)", 0, int),
                envelopes=g(r"'member_fallback': (\d+)", 0, int),
                joist_envelopes=g(r"'joist_envelope': (\d+)", 0, int), holes=g(r"'holes': (\d+)", 0, int),
                steel_ratio=g(r"ratio ([\d.]+)", None, float), solids=g(r"(\d+) top-level shapes", None, int),
                valid=g(r"BRep valid: (\d+)", None, int), seconds=g(r"converted in (\d+)s", None, int))


def convert(job, outdir, name, a, cpu):
    res = {}
    for stage in ((1, 2) if a.stage == "both" else (int(a.stage),)):
        step = os.path.join(outdir, f"{name}_stage{stage}.step")
        cmd = [sys.executable, "-u", os.path.join(DECODE, "sds2_to_step.py"), job, "-o", step, "--stage", str(stage)]
        if not a.no_verify: cmd.append("--verify")
        if stage == 2:
            cmd += [f for f, on in (("--flat", a.flat), ("--no-holes", a.no_holes), ("--no-bolts", a.no_bolts)) if on]
        with cpu:
            while free_ram_gb() < a.min_free_gb or shutil.disk_usage(os.path.dirname(os.path.abspath(a.out)) or ".").free / 2 ** 30 < a.min_disk_gb:
                time.sleep(15)
            t = time.time()
            try:
                p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                                   timeout=a.timeout, env=dict(os.environ, PYTHONUNBUFFERED="1"))
                txt, rc = p.stdout, p.returncode
            except subprocess.TimeoutExpired as e:
                txt, rc = (e.stdout or "") if isinstance(e.stdout, str) else "", "timeout"
        keep = "\n".join(l for l in txt.splitlines() if not l.startswith("*") and "Transferr" not in l and l.strip())
        open(os.path.join(outdir, f"{name}_stage{stage}.log"), "w", encoding="utf-8").write(keep)
        r = parse_log(txt); r.update(rc=rc, wall_s=round(time.time() - t),
                                     step_mb=round(os.path.getsize(step) / 2 ** 20, 1) if os.path.exists(step) else None)
        if rc != 0: r["error"] = keep[-400:]
        res[f"stage{stage}"] = r
    return res


def qa(rec):
    """Accuracy verdict for one job: 'pass', 'warn' or 'fail' + reasons, from the converter's own checks."""
    if rec.get("status") in ("error", "failed"):
        return "fail", [error_class(rec)]
    s = rec.get("stage2") or {}
    why = []
    if rec.get("status") == "ok_stage1":
        return "warn", ["stage 2 failed: members only (stage 1)"]
    n = (s.get("plate") or 0) + (s.get("rolled") or 0) + (s.get("fastener") or 0)
    if s.get("solids") is not None and s.get("valid") is not None and s["valid"] < s["solids"]:
        bad = s["solids"] - s["valid"]
        why.append(f"{bad} invalid solid(s) after read-back")
        if bad > max(5, 0.001 * s["solids"]): return "fail", why
    r = s.get("steel_ratio")
    if r is None and n:
        why.append("no steel weight check (no SDS2 piece weights)")
    elif r is not None and not 0.9 <= r <= 1.1:
        why.append(f"steel weight {r:.3f} x SDS2")
        if not 0.75 <= r <= 1.3: return "fail", why
    if n and (s.get("skipped") or 0) > 0.01 * n: why.append(f"{s['skipped']} pieces not built")
    npr = (s.get("plate") or 0) + (s.get("rolled") or 0)          # studs / rods are true cylinders by design
    if npr and (s.get("exact") or 0) < 0.9 * npr: why.append(f"exact geometry for {min(1, s['exact'] / npr):.0%} of plates/rolled")
    if s.get("joist_envelopes"):
        why.append(f"{s['joist_envelopes']} joists represented only by approximate member envelopes")
    if not n: why.append("no fabricated pieces (member envelopes only)")
    return ("warn" if why else "pass"), why


def error_class(rec):
    """Short, groupable failure reason."""
    s = rec.get("stage2") or rec.get("stage1") or {}
    if s.get("rc") == "timeout": return "timeout"
    e = rec.get("error") or s.get("error") or ""
    for pat, lab in ((r"no SDS2 job folder", "no job folder in archive"), (r"incomplete", "job folder incomplete"),
                     (r"NoSuchKey|AccessDenied|botocore|EndpointConnection", "S3 access"),
                     (r"Bad7zFile|BadZipFile|CRC|UnsupportedCompression|lzma|Unsupported", "archive unreadable"),
                     (r"unsupported job_mtrl layout", "unsupported job_mtrl layout"), (r"MemoryError", "out of memory"),
                     (r"No space left", "disk full"), (r"FileNotFoundError", "missing job file"),
                     (r"STEP write failed", "STEP write failed")):
        if re.search(pat, e): return lab
    m = re.findall(r"(\w+Error|\w+Exception)", e)
    return m[-1] if m else "other"


def process(it, a, done, cpu, dl, outp):
    if it["jobs"] is None and any(k[0] == it["archive"] for k in done):
        return                                     # local archive whose jobs were found by scanning: already done
    todo = [j for j in (it["jobs"] or [(None, None)]) if not ((it["archive"], j[0]) in done)]
    if not todo: return
    tag = hashlib.md5(it["archive"].encode()).hexdigest()[:8]
    work = lp(os.path.join(a.work, tag)); shutil.rmtree(work, ignore_errors=True); os.makedirs(work, exist_ok=True)
    try:
        if it["kind"] == "dir":
            jobs = [("", it["archive"])]
        else:
            with dl: jobs = extract(dict(it, jobs=[j for j in todo if j[0] is not None] or None), work, a.stream_gb,
                                    not a.no_7z_cli)
        if not jobs:
            raise RuntimeError("no SDS2 job folder (main/jsetup) in archive")
        for root, job in jobs:
            rec = dict(archive=it["archive"], job_root=root, source=it["kind"], archive_gb=round(it["size"] / 1e9, 3))
            try:
                if not is_job(job):
                    raise RuntimeError("job folder incomplete (main/job_mtrl or mem/mem_idx missing)")
                ver = read_version(job)
                name = safe(os.path.basename(root.rstrip("/\\")) if root else os.path.basename(job)) + "_" + \
                       hashlib.md5((it["archive"] + "|" + root).encode()).hexdigest()[:6]
                outdir = os.path.join(a.out, safe(ver, 12), name); os.makedirs(outdir, exist_ok=True)
                rec.update(version=ver, name=name, outdir=outdir, **convert(lp(job), outdir, name, a, cpu))
                st = rec.get("stage2") or rec.get("stage1")
                rec["status"] = "ok" if st and st["rc"] == 0 else "failed"
                if rec["status"] == "failed" and a.stage == "2" and not a.no_fallback:
                    # stage 2 failed (damaged piece table, unknown piece layout ...): members-only stage 1 instead
                    b = dict(vars(a)); b["stage"] = "1"
                    rec.update(convert(lp(job), outdir, name, argparse.Namespace(**b), cpu))
                    if rec["stage1"]["rc"] == 0: rec["status"] = "ok_stage1"
            except Exception as e:
                rec.update(status="error", error=f"{type(e).__name__}: {e}"[:400])
            log(rec, outp, a)
    except Exception as e:
        log(dict(archive=it["archive"], job_root=None, source=it["kind"], status="error",
                 error=f"{type(e).__name__}: {e}"[:400]), outp, a)
    finally:
        if not a.keep_extracted: shutil.rmtree(work, ignore_errors=True)


def s3uri(u):
    m = re.match(r"s3://([^/]+)/?(.*)", u or "")
    if not m: raise SystemExit(f"--upload needs s3://bucket/prefix, got {u!r}")
    return m.group(1), m.group(2).strip("/")


def upload_dir(outdir, rel, a):
    """Push a finished job's outputs to --upload (s3://bucket/prefix/<version>/<name>/...), optionally delete them."""
    import boto3
    bkt, pre = s3uri(a.upload); s3 = boto3.client("s3")
    for f in os.listdir(outdir):
        s3.upload_file(os.path.join(outdir, f), bkt, "/".join(x for x in (pre, rel, f) if x))
    if a.delete_local: shutil.rmtree(outdir, ignore_errors=True)
    return f"s3://{bkt}/{'/'.join(x for x in (pre, rel) if x)}/"


_last_sync = [0.0]


def sync_results(outp, a, force=False):
    """Copy results.jsonl to --upload so a new instance can resume (at most once a minute unless forced)."""
    if not a.upload or (not force and time.time() - _last_sync[0] < 60): return
    import boto3
    bkt, pre = s3uri(a.upload)
    boto3.client("s3").upload_file(outp, bkt, "/".join(x for x in (pre, "results.jsonl") if x))
    _last_sync[0] = time.time()


def log(rec, outp, a=None):
    rec["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    rec["qa"], rec["qa_reasons"] = qa(rec)
    if a is not None and a.upload and rec.get("outdir") and os.path.isdir(rec["outdir"]):
        try:
            rec["s3"] = upload_dir(rec["outdir"], os.path.relpath(rec["outdir"], a.out).replace("\\", "/"), a)
        except Exception as e:
            rec["upload_error"] = f"{type(e).__name__}: {e}"[:300]
    with lock:
        with open(outp, "a", encoding="utf-8") as f: f.write(json.dumps(rec) + "\n")
        if a is not None:
            try: sync_results(outp, a)
            except Exception as e: print("results sync failed:", e, flush=True)
        s = rec.get("stage2") or rec.get("stage1") or {}
        print(f"[{rec['status']:6s}|{rec['qa']:4s}] {rec.get('version', '?'):8s} {str(s.get('valid'))}/{str(s.get('solids'))} valid  "
              f"ratio {s.get('steel_ratio')}  {rec['archive'][-60:]} :: {rec.get('job_root')}", flush=True)


def summarize(outp, out):
    last = {}
    for line in open(outp, encoding="utf-8"):
        r = json.loads(line); last[(r["archive"], r.get("job_root"))] = r
    rows = list(last.values())
    for r in rows:                                              # re-grade with the current rules
        r["qa"], r["qa_reasons"] = qa(r)
    cols = ["qa", "qa_reasons", "status", "version", "archive", "job_root", "exact", "plate", "rolled", "fastener",
            "bolts", "bolts_sds2", "bolts_nominal", "skipped", "envelopes", "joist_envelopes", "holes", "steel_ratio", "solids", "valid",
            "seconds", "step_mb", "s3", "outdir", "error"]
    with open(os.path.join(out, "summary.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore"); w.writeheader()
        for r in rows:
            w.writerow({**r, **(r.get("stage2") or r.get("stage1") or {}), "status": r["status"], "version": r.get("version"),
                        "qa_reasons": "; ".join(r["qa_reasons"])})
    by = collections.defaultdict(collections.Counter)
    for r in rows: by[(r.get("version") or "?")[:3]][r["status"]] += 1
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write("| version | ok (stage 2) | ok (stage 1 only) | failed | error |\n|---|---:|---:|---:|---:|\n")
        for v in sorted(by): f.write(f"| {v} | {by[v]['ok']} | {by[v]['ok_stage1']} | {by[v]['failed']} | {by[v]['error']} |\n")
        tot = collections.Counter(r["status"] for r in rows)
        f.write(f"| **all** | {tot['ok']} | {tot['ok_stage1']} | {tot['failed']} | {tot['error']} |\n")
        # accuracy verdicts, per version
        q = collections.defaultdict(collections.Counter)
        for r in rows: q[(r.get("version") or "?")[:3]][r["qa"]] += 1
        f.write("\n### Accuracy verdict\n\n| version | pass | warn | fail |\n|---|---:|---:|---:|\n")
        for v in sorted(q): f.write(f"| {v} | {q[v]['pass']} | {q[v]['warn']} | {q[v]['fail']} |\n")
        qt = collections.Counter(r["qa"] for r in rows)
        f.write(f"| **all** | {qt['pass']} | {qt['warn']} | {qt['fail']} |\n")
        # why: warn reasons and failure classes, most frequent first (with an example archive each)
        for lab, sel in (("Warnings", "warn"), ("Failures", "fail")):
            c = collections.Counter(); ex = {}
            for r in rows:
                if r["qa"] != sel: continue
                for why in r["qa_reasons"]:
                    k = re.sub(r"[\d.]+", "#", why); c[k] += 1; ex.setdefault(k, r["archive"])
            if c:
                f.write(f"\n### {lab}\n\n| reason | jobs | example archive |\n|---|---:|---|\n")
                for k, v in c.most_common(): f.write(f"| {k} | {v} | {ex[k]} |\n")
    print("summary:", dict(collections.Counter(r["status"] for r in rows)), "qa:", dict(collections.Counter(r["qa"] for r in rows)),
          "->", os.path.join(out, "summary.md"))


def main():
    cores = os.cpu_count() or 4
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--s3", action="store_true"); src.add_argument("--local")
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "batch"))
    ap.add_argument("--work", default=os.path.join(ROOT, "work"), help="scratch folder for extracted jobs")
    ap.add_argument("--versions", nargs="+", help='version prefixes, e.g. "7.0,7.1" or 7.3 2019 (quote in PowerShell)')
    ap.add_argument("--match"); ap.add_argument("--items")
    ap.add_argument("--include-junk", action="store_true"); ap.add_argument("--min-members", type=int, default=1)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--stage", choices=("1", "2", "both"), default="2")
    ap.add_argument("--flat", action="store_true"); ap.add_argument("--no-holes", action="store_true")
    ap.add_argument("--no-bolts", action="store_true"); ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--convert-jobs", type=int, default=max(1, min(cores - 1, int(free_ram_gb() // 3))),
                    help="conversions at once (default: cores-1, at most free RAM / 3 GB)")
    ap.add_argument("--workers", type=int, help="archives in flight (default: convert-jobs + 2)")
    ap.add_argument("--downloads", type=int, default=3, help="concurrent downloads / extractions")
    ap.add_argument("--min-free-gb", type=float, default=2.5); ap.add_argument("--min-disk-gb", type=float, default=20)
    ap.add_argument("--timeout", type=int, default=4 * 3600, help="per conversion, seconds")
    ap.add_argument("--retry-failed", action="store_true"); ap.add_argument("--keep-extracted", action="store_true")
    ap.add_argument("--no-fallback", action="store_true", help="don't fall back to stage 1 when stage 2 fails")
    ap.add_argument("--upload", help="s3://bucket/prefix: push each finished job's outputs + results.jsonl there")
    ap.add_argument("--delete-local", action="store_true", help="with --upload: delete a job's local outputs once uploaded")
    ap.add_argument("--stream-gb", type=float, default=20,
                    help=".7z archives larger than this are streamed from S3 by py7zr unless the disk can take a local copy for the 7-Zip CLI")
    ap.add_argument("--no-7z-cli", action="store_true", help="use py7zr only, even when a 7-Zip binary (7zz / 7z / 7za) is installed")
    ap.add_argument("--plan", action="store_true", help="list what would run and exit (no S3 access)")
    a = ap.parse_args()
    items = s3_items(a) if a.s3 else local_items(a)
    njobs = sum(len(i["jobs"] or [1]) for i in items)
    byv = collections.Counter(v[:3] for i in items for _, v in (i["jobs"] or [("", "unknown")]))
    print(f"{len(items)} archives/folders, {njobs} jobs, {sum(i['size'] for i in items) / 1e9:.1f} GB; by version {dict(byv)}; "
          f"{a.convert_jobs} conversions at once; 7z via {'py7zr' if a.no_7z_cli or not seven_zip_cli() else seven_zip_cli() + ' (py7zr fallback)'}")
    if a.plan: return
    os.makedirs(a.out, exist_ok=True); os.makedirs(a.work, exist_ok=True)
    outp = os.path.join(a.out, "results.jsonl"); done = set()
    if a.upload and not os.path.exists(outp):
        # new / replacement instance: continue from the results already uploaded
        import boto3
        bkt, pre = s3uri(a.upload)
        try:
            boto3.client("s3").download_file(bkt, "/".join(x for x in (pre, "results.jsonl") if x), outp)
            print("resuming from", a.upload.rstrip("/") + "/results.jsonl")
        except Exception:
            pass
    if os.path.exists(outp):
        for line in open(outp, encoding="utf-8"):
            r = json.loads(line)
            if r["status"] in ("ok", "ok_stage1") or not a.retry_failed: done.add((r["archive"], r.get("job_root")))
    cpu = threading.BoundedSemaphore(a.convert_jobs); dl = threading.BoundedSemaphore(a.downloads)
    with ThreadPoolExecutor(a.workers or a.convert_jobs + 2) as ex:
        for f in [ex.submit(process, it, a, done, cpu, dl, outp) for it in items]: f.result()
    summarize(outp, a.out)
    if a.upload:
        sync_results(outp, a, force=True)
        import boto3
        bkt, pre = s3uri(a.upload)
        for f in ("summary.csv", "summary.md"):
            boto3.client("s3").upload_file(os.path.join(a.out, f), bkt, "/".join(x for x in (pre, f) if x))


if __name__ == "__main__":
    main()
