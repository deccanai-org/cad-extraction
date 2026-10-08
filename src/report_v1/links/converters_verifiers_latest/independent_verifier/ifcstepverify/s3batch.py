"""Batch verification straight from S3 (EC2). Packages are directories holding manifest.jsonl with model/step/*.step and
model/ifc/*.ifc beside it (projpkg4 layout). Every STEP is verified against the IFCs of its own package.

Resumable (results.jsonl, kept locally and in the output prefix), memory-aware parallel, each STEP in its own process."""
import os, sys, re, json, time, random, shutil, hashlib, threading, subprocess, collections
from concurrent.futures import ThreadPoolExecutor, as_completed
from . import config as C

lock = threading.Lock()


def s3uri(u):
    m = re.match(r"s3://([^/]+)/?(.*)", u or "")
    if not m: raise SystemExit(f"need s3://bucket/prefix, got {u!r}")
    return m.group(1), m.group(2).rstrip("/") + "/" if m.group(2) else ""


def client():
    import boto3, botocore
    return boto3.client("s3", config=botocore.config.Config(max_pool_connections=64, retries={"max_attempts": 10, "mode": "adaptive"}))


def free_ram_gb():
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable"): return int(line.split()[1]) / 2 ** 20
    except OSError:
        pass
    try:
        import ctypes
        class M(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("t", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong),
                        ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
        m = M(); m.l = ctypes.sizeof(M); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)); return m.a / 2 ** 30
    except Exception:
        return 1e9


# ------------------------------------------------------------------------------------------------ inventory
def inventory(src, threads=48, cache=None, project_filter=None):
    """-> {package_prefix: {"manifest": key, "steps": [(key, size)], "ifcs": [(key, size)]}}. Lists projects in parallel."""
    if cache and os.path.exists(cache):
        return json.load(open(cache, encoding="utf-8"))
    bkt, pre = s3uri(src); s3 = client()
    projects = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bkt, Prefix=pre, Delimiter="/"):
        projects += [c["Prefix"] for c in page.get("CommonPrefixes", [])]
    if project_filter: projects = [p for p in projects if re.search(project_filter, p[len(pre):], re.I)]
    def lst(p):
        out = []
        for page in client().get_paginator("list_objects_v2").paginate(Bucket=bkt, Prefix=p):
            out += [(o["Key"], o["Size"], o["LastModified"].isoformat()) for o in page.get("Contents", [])]
        return out
    objs = []
    with ThreadPoolExecutor(threads) as ex:
        for r in ex.map(lst, projects): objs += r
    pk = collections.defaultdict(lambda: {"manifest": None, "steps": [], "ifcs": [], "last_modified": ""})
    for k, sz, t in objs:
        m = re.match(r"(.*/)(manifest\.jsonl|model/step/[^/]+\.(?:step|stp)|model/ifc/[^/]+\.ifc)$", k, re.I)
        if not m: continue
        root, rest = m.group(1), m.group(2).lower()
        d = pk[root]; d["last_modified"] = max(d["last_modified"], t)
        if rest == "manifest.jsonl": d["manifest"] = k
        elif rest.startswith("model/step/"): d["steps"].append([k, sz])
        else: d["ifcs"].append([k, sz])
    inv = {k: dict(v, steps=sorted(v["steps"]), ifcs=sorted(v["ifcs"])) for k, v in sorted(pk.items()) if v["steps"]}
    if cache:
        os.makedirs(os.path.dirname(os.path.abspath(cache)), exist_ok=True); json.dump(inv, open(cache, "w", encoding="utf-8"))
    return inv


def select(inv, src, a):
    """Work list [(package, step_key, size)], deterministic for a given --seed."""
    _, pre = s3uri(src)
    items = [(p, k, sz) for p, d in inv.items() for k, sz in d["steps"]]
    if a.match: items = [x for x in items if re.search(a.match, x[1], re.I)]
    if a.max_step_gb: items = [x for x in items if x[2] <= a.max_step_gb * 1e9]      # filters first, then sampling
    if a.projects_recent:
        proj_time = collections.defaultdict(str)
        for p, d in inv.items(): proj = p[len(pre):].split("/")[0]; proj_time[proj] = max(proj_time[proj], d["last_modified"])
        keep = set(sorted(proj_time, key=lambda x: (proj_time[x], x), reverse=True)[:a.projects_recent])
        items = [x for x in items if x[1][len(pre):].split("/")[0] in keep]
    if a.per_project:
        rng = random.Random(a.seed); by = collections.defaultdict(list)
        for x in sorted(items): by[x[1][len(pre):].split("/")[0]].append(x)
        items = [y for proj in sorted(by) for y in rng.sample(by[proj], min(a.per_project, len(by[proj])))]
    if a.sample:
        items = random.Random(a.seed).sample(sorted(items), min(a.sample, len(items)))
    return sorted(items)


# ------------------------------------------------------------------------------------------------ run
class Out:
    """Output location: s3://bucket/prefix/ or a local folder (for tests / runs without an output bucket)."""
    def __init__(self, uri):
        self.local = not uri.startswith("s3://")
        if self.local: self.dir = os.path.abspath(uri); os.makedirs(self.dir, exist_ok=True)
        else: self.b, self.p = s3uri(uri)
    def put(self, path, rel):
        if self.local:
            d = os.path.join(self.dir, *rel.split("/")); os.makedirs(os.path.dirname(d), exist_ok=True); shutil.copyfile(path, d)
        else: client().upload_file(path, self.b, self.p + rel)
    def get(self, rel, path):
        if self.local:
            s = os.path.join(self.dir, *rel.split("/"))
            if not os.path.exists(s): raise FileNotFoundError(s)
            shutil.copyfile(s, path)
        else: client().download_file(self.b, self.p + rel, path)
    def uri(self, rel): return os.path.join(self.dir, rel) if self.local else f"s3://{self.b}/{self.p}{rel}"


def run(a):
    src_b, _ = s3uri(a.src); O = Out(a.out)
    work = os.path.abspath(a.work); os.makedirs(work, exist_ok=True)
    inv = inventory(a.src, cache=os.path.join(work, "inventory.json") if not a.refresh_inventory else None, project_filter=a.project_filter)
    items = select(inv, a.src, a)
    resp = os.path.join(work, "results.jsonl")
    if not os.path.exists(resp):
        try: O.get("results.jsonl", resp); print("resuming from", O.uri("results.jsonl"), flush=True)
        except Exception: pass
    done = set()
    if os.path.exists(resp):
        for l in open(resp, encoding="utf-8"):
            r = json.loads(l)
            if r.get("verdict") not in ("ERROR", None) or not a.retry_errors: done.add(r["step_key"])
    todo = [x for x in items if x[1] not in done]
    by_pkg = collections.defaultdict(list)
    for p, k, sz in todo: by_pkg[p].append((k, sz))
    print(f"{len(items)} STEP files selected, {len(done)} already done, {len(todo)} to verify in {len(by_pkg)} packages; "
          f"{a.workers} package workers, RAM free {free_ram_gb():.1f} GB", flush=True)
    if a.plan: return
    last_sync = [0.0]
    def log(rec):
        with lock:
            with open(resp, "a", encoding="utf-8") as f: f.write(json.dumps(rec, sort_keys=True) + "\n")
            if time.time() - last_sync[0] > 60:
                try: O.put(resp, "results.jsonl"); last_sync[0] = time.time()
                except Exception as e: print("results sync failed:", e, flush=True)
            print(f"[{rec['verdict']:12s}] {rec.get('t_total_s', '?')}s {rec['step_key'][-90:]}  {','.join(rec.get('codes', []))[:160]}", flush=True)
    def package(pkg):
        c = client(); tag = hashlib.sha1(pkg.encode()).hexdigest()[:12]; pdir = os.path.join(work, "pkg", tag)
        shutil.rmtree(pdir, ignore_errors=True); os.makedirs(os.path.join(pdir, "model", "ifc"), exist_ok=True)
        try:
            d = inv[pkg]; man = None
            if d["manifest"]:
                mp = os.path.join(pdir, "manifest.jsonl"); c.download_file(src_b, d["manifest"], mp); man = mp
            while free_ram_gb() < a.min_free_gb: time.sleep(15)
            ifc_local = []
            for k, sz in d["ifcs"]:
                lp_ = os.path.join(pdir, *k[len(pkg):].split("/")); os.makedirs(os.path.dirname(lp_), exist_ok=True); c.download_file(src_b, k, lp_); ifc_local.append(lp_)
            for k, sz in sorted(by_pkg[pkg]):
                while free_ram_gb() < a.min_free_gb: time.sleep(15)
                sl = os.path.join(pdir, "step" + os.path.splitext(k)[1]); stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", k[len(pkg):])[-150:]
                rec = dict(step_key=k, package=pkg, bytes=sz)
                try:
                    c.download_file(src_b, k, sl)
                    od = os.path.join(pdir, "out")
                    cmd = [sys.executable, "-m", "ifcstepverify", "pair", "--step", sl, "--ifc-dir", os.path.join(pdir, "model", "ifc"), "--ifc-base", pdir,
                           "--step-relpath", k[len(pkg):], "--out", od, "--stem", stem, "--threads", str(a.threads),
                           "--cand-workers", str(a.cand_workers), "--step-geom-max", str(a.step_geom_max), "--ifc-geom-max", str(a.ifc_geom_max)]
                    if man: cmd += ["--manifest", man]
                    p = subprocess.run(cmd, capture_output=True, text=True, timeout=a.timeout,
                                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    jp = os.path.join(od, stem + ".json")
                    if p.returncode != 0 or not os.path.exists(jp): raise RuntimeError((p.stderr or p.stdout)[-400:])
                    J = json.load(open(jp, encoding="utf-8")); R = J["result"]
                    for fn in (stem + ".json", stem + "_elements.csv"):
                        O.put(os.path.join(od, fn), "files/" + k[len(s3uri(a.src)[1]):].rsplit("/", 1)[0] + "/" + fn)
                    rec.update(verdict=R["verdict"], pipeline_issue=R["pipeline_issue"], cause_classes=R["cause_classes"],
                               codes=[r["code"] for r in R["reasons"] if r["level"] != "INFO"], info=[r["code"] for r in R["reasons"] if r["level"] == "INFO"],
                               writer=R["step"]["writer"], step_elements=R.get("step_elements"),
                               source=(R.get("source") or {}).get("best", {}) and R["source"]["best"].get("rel"),
                               overlap=(R.get("source") or {}).get("best", {}) and R["source"]["best"].get("overlap"),
                               result_digest=R["result_digest"], t_total_s=J["run"]["t_total_s"])
                    shutil.rmtree(od, ignore_errors=True)
                except subprocess.TimeoutExpired:
                    rec.update(verdict="ERROR", codes=["E_TIMEOUT"], error=f"timeout after {a.timeout}s")
                except Exception as e:
                    rec.update(verdict="ERROR", codes=["E_RUN"], error=f"{type(e).__name__}: {e}"[:500])
                finally:
                    if os.path.exists(sl): os.remove(sl)
                log(rec)
        except Exception as e:
            for k, sz in by_pkg[pkg]:
                log(dict(step_key=k, package=pkg, bytes=sz, verdict="ERROR", codes=["E_PACKAGE"], error=f"{type(e).__name__}: {e}"[:500]))
        finally:
            shutil.rmtree(pdir, ignore_errors=True)
    # biggest packages first so they don't all land at the end
    order = sorted(by_pkg, key=lambda p: -sum(sz for _, sz in inv[p]["ifcs"]) - sum(sz for _, sz in by_pkg[p]))
    with ThreadPoolExecutor(a.workers) as ex:
        for f in as_completed([ex.submit(package, p) for p in order]): f.result()
    O.put(resp, "results.jsonl")
    from .report import build
    paths = build(resp, work)
    for pth in paths: O.put(pth, os.path.basename(pth))
    print("done:", ", ".join(O.uri(os.path.basename(p)) for p in paths), flush=True)
