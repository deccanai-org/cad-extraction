#!/usr/bin/env python3
"""DB1 -> STEP production worker (Linux).

Job pool: _control/db1-v2/db1_jobs.json (distinct DB1 by sha256: every UNSUPPORTED and
FAILED file of the old converter). Only engines marked approved in layouts.json run.
Per job: decode (db1dec, version layout re-verified per file) -> IFC of Tekla-exact
extrusions (db1step) -> lead's ifc2step5.py --mode hybrid --prec 2 -> STEP -> flavour
markers + OCC read-back (lead's validate_step.py) -> upload -> result JSON.

Writes only:
  cad-disk-extract/conversions/db1-step/<sha>.stp
  cad-disk-extract/_state/db1-v2/{claims,results,deferred,hosts,logs}/...
"""
import sys, json, os, platform, subprocess, sys, threading, time, traceback, urllib.request
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

B = "annotationprod"; R = "cad-disk-extract"
CTL = f"{R}/_control/db1-v2"; ST = f"{R}/_state/db1-v2"; OUT = f"{R}/conversions/db1-step"
HOST = platform.node()
WORK = os.environ.get("DB1_WORK", "/opt/db1v2")
MAMBA = os.path.join(WORK, "mamba"); ENVP = os.path.join(MAMBA, "envs", "occ")
PY = os.path.join(ENVP, "bin", "python")
SLOTS = int(os.environ.get("DB1_SLOTS", str(max(1, (os.cpu_count() or 4) - 2))))
STALE = 2400; RB_MAX = 64 << 20; TIMEOUT = 7200; STEP_TIMEOUT = 21600
# results from older decoder code count as NOT done: bumping CODE re-runs every file on the
# new code without purging anything (old outputs are overwritten, or removed when a re-run no
# longer yields a verified model)
CODE = "db1-2026-09-25g"
# code g: the STEP step runs on ifcopenshell 0.8.4 (0.8.5 hangs on boolean cuts of hollow sections).
# Everything final under f is kept; only STEP-step failures/timeouts (and anything unfinished) re-run.
_KEEP_NONOK = {"empty_model", "no_member_layout", "no_resolvable_members", "bad_output", "deferred_layout"}
KEEP = {c: _KEEP_NONOK for c in ("db1-2026-09-25b", "db1-2026-09-25c", "db1-2026-09-25d", "db1-2026-09-25e")}
KEEP["db1-2026-09-25f"] = _KEEP_NONOK | {"ok", "suspect_orientation", "suspect_attr_link", "convert_error"}
PY84 = "/opt/ifc84/bin/python"


def kept(r):
    return r.get("status") in KEEP.get(r.get("code"), ())


s3 = boto3.client("s3", region_name="ap-south-1",
                  config=Config(max_pool_connections=64, retries={"max_attempts": 10, "mode": "adaptive"}))
LOGLOCK = threading.Lock(); LOGBUF = []
PROCS = {}; PLOCK = threading.Lock(); KILLED = set(); NEED = {}


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    with LOGLOCK:
        LOGBUF.append(line); del LOGBUF[:-500]


def now(): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
def put(key, obj): s3.put_object(Bucket=B, Key=key, Body=json.dumps(obj, default=str).encode(), ContentType="application/json")


def exists(key):
    try: s3.head_object(Bucket=B, Key=key); return True
    except ClientError: return False


WRITER = "cut-snap"   # db1step snaps near-axis cut frames (a 0.01 deg-off flange cut hung OpenCASCADE for 6 h)


def done_now(sha):
    """a result exists AND it was produced by this code version; a STEP-stage failure written before the
    cut-snap writer existed is re-run once with it"""
    try:
        r = json.loads(s3.get_object(Bucket=B, Key=f"{ST}/results/{sha}.json")["Body"].read())
        if r.get("code") == CODE and r.get("status") == "step_fail" and not r.get("writer"):
            return False
        if r.get("code") == CODE and r.get("status") == "step_fail" and r.get("arc_writer") and r.get("step_rc") in (-11, 139, 124, 125) and not r.get("rescue"):
            return False
        # arc fix: outputs with contour plates on a chamfer layout, made before the arc2 writer, are re-checked
        # (re-decoded; a new STEP only when a plate outline actually changes); STEP failures get one more try
        if not r.get("arc_writer") and r.get("code") in (CODE, "db1-2026-09-25f") and (
                (r.get("status") == "ok" and ((r.get("convert") or {}).get("sources") or {}).get("contour_plate", 0) > 0
                 and (r.get("layout") or {}).get("poly_ch")) or (r.get("status") == "step_fail" and r.get("code") == CODE)):
            return False
        return r.get("code") == CODE or kept(r)
    except ClientError: return False
    except Exception: return False


def not_done(jobs):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(48) as ex:
        flags = list(ex.map(lambda j: done_now(j["sha"]), jobs))
    return [j for j, f in zip(jobs, flags) if not f]


def mem():
    d = {}
    for ln in open("/proc/meminfo"):
        k, v = ln.split(":"); d[k] = int(v.split()[0]) * 1024
    return d["MemTotal"], d["MemAvailable"]


def setup_env():
    os.makedirs(WORK, exist_ok=True)
    src = os.path.join(WORK, "src"); os.makedirs(src, exist_ok=True)
    for f in ("db1dec.py", "db1step.py", "convert_one.py", "db1old.py"):
        s3.download_file(B, f"{CTL}/src/{f}", os.path.join(src, f))
    for f in ("ifc2step5.py", "validate_step.py"):
        s3.download_file(B, f"{R}/_control/ifc-step/{f}", os.path.join(WORK, f))
    s3.download_file(B, f"{CTL}/tekla_profiles.json", os.path.join(WORK, "tekla_profiles.json"))
    if not os.path.exists(PY84) and os.path.exists(PY):
        subprocess.run([PY, "-m", "venv", "/opt/ifc84"], check=False)
        subprocess.run([PY84, "-m", "pip", "install", "-q", "ifcopenshell==0.8.4.post1", "numpy"], check=False)
    if os.path.exists(PY): return
    log("building conda env")
    mm = os.path.join(WORK, "micromamba")
    if not os.path.exists(mm):
        url = "https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-linux-64"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "curl/8"}), timeout=300) as r, open(mm, "wb") as o:
            o.write(r.read())
        os.chmod(mm, 0o755)
    r = subprocess.run([mm, "create", "-y", "-p", ENVP, "-c", "conda-forge", "python=3.11", "ifcopenshell",
                        "pythonocc-core", "numpy", "lark"], env=dict(os.environ, MAMBA_ROOT_PREFIX=MAMBA),
                       capture_output=True, text=True)
    if r.returncode or not os.path.exists(PY):
        raise RuntimeError("env build failed: " + r.stdout[-1500:] + r.stderr[-1500:])
    log("env ready")


def claim(jid):
    key = f"{ST}/claims/{jid}.json"; body = json.dumps({"host": HOST, "at": now()}).encode()
    try:
        s3.put_object(Bucket=B, Key=key, Body=body, IfNoneMatch="*"); return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") not in ("PreconditionFailed", "412", "ConditionalRequestConflict", "409"): raise
    try: age = time.time() - s3.head_object(Bucket=B, Key=key)["LastModified"].timestamp()
    except ClientError: return False
    if age < STALE: return False
    try:
        s3.delete_object(Bucket=B, Key=key); s3.put_object(Bucket=B, Key=key, Body=body, IfNoneMatch="*")
        log(f"took over stale claim {jid}"); return True
    except ClientError: return False


def touch(jid):
    try: s3.put_object(Bucket=B, Key=f"{ST}/claims/{jid}.json", Body=json.dumps({"host": HOST, "at": now(), "refresh": True}).encode())
    except Exception: pass


def run(jid, cmd, logf, timeout, stall=None):
    """rc of cmd; 124 = overall timeout; 125 = stalled (log unchanged for `stall` s: the converter prints
    progress every 5,000 parts, so a silent half hour is an element the kernel never finishes)"""
    total, _ = mem()
    cmd = ["systemd-run", "--scope", "--quiet", "-p", f"MemoryMax={int(total * 0.85)}", "-p", "MemorySwapMax=0"] + cmd
    with open(logf, "a") as lf:
        p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT)
        with PLOCK: PROCS[jid] = (p, time.time())
        try:
            t0 = time.time(); last_size = -1; last_change = t0; rc = None
            while rc is None:
                try:
                    rc = p.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    now_t = time.time()
                    if now_t - t0 > timeout:
                        p.kill(); p.wait(); rc = 124; break
                    if stall:
                        try: sz = os.path.getsize(logf)
                        except OSError: sz = last_size
                        if sz != last_size: last_size = sz; last_change = now_t
                        elif now_t - last_change > stall:
                            p.kill(); p.wait(); rc = 125; break
        finally:
            with PLOCK: PROCS.pop(jid, None)
    return rc


def count(path, pats):
    c = {p: 0 for p in pats}
    with open(path, "rb") as f:
        for ln in f:
            for p in pats:
                if p in ln: c[p] += ln.count(p)
    return c


def crash_rescue(jid, ifc, stp, logf, step_py, d):
    """bisect the intermediate IFC to the elements the kernel crashes on (tools shared with the IFC finisher),
    drop only their representation (capped at max(50, 1%)), convert again"""
    info = {"at": now()}
    try:
        rd = os.path.join(WORK, "rescue"); os.makedirs(rd, exist_ok=True)
        for t in ("ifc_crash_bisect.py", "ifc_exclude.py"):
            s3.download_file(B, f"{R}/_control/ifc-step/rescue/{t}", os.path.join(rd, t))
        p = subprocess.run([step_py, os.path.join(rd, "ifc_crash_bisect.py"), ifc, os.path.join(WORK, "ifc2step5.py"), "16", "120"],
                           capture_output=True, text=True, timeout=4 * 3600)
        lines = p.stdout.strip().splitlines()
        if not lines: info["result"] = f"bisect produced no result (rc {p.returncode})"; return info
        res = json.loads(lines[-1]); culprits = res["culprits"]
        info.update(tessellate_set=res["tessellate_set"], culprits=len(culprits), bisect_secs=res["secs"])
        cap = max(50, res["tessellate_set"] // 100)
        if not culprits: info["result"] = "no crashing element isolated"; return info
        if len(culprits) > cap: info["result"] = f"too many crashing elements ({len(culprits)} > {cap})"; return info
        fixed = os.path.join(d, "fixed.ifc")
        ex = subprocess.run([step_py, os.path.join(rd, "ifc_exclude.py"), ifc, fixed] + [c["guid"] for c in culprits], capture_output=True, text=True, timeout=3600)
        info["excluded"] = json.loads(ex.stdout.strip().splitlines()[-1])
        for f in (stp, stp + ".stats.json"):
            try: os.remove(f)
            except OSError: pass
        rc = run(jid, [step_py, os.path.join(WORK, "ifc2step5.py"), fixed, stp, "--mode", "hybrid", "--prec", "2", "--threads", "4"], logf, STEP_TIMEOUT, stall=1800)
        info["rc"] = rc; info["result"] = f"converted without {len(culprits)} crashing element(s)" if rc == 0 else f"still fails (rc {rc})"
    except Exception as e:
        info["result"] = f"rescue error: {type(e).__name__}: {str(e)[:200]}"
    return info


def process(job, layouts):
    jid = job["sha"]; d = os.path.join(WORK, "jobs", jid); os.makedirs(d, exist_ok=True)
    db1 = os.path.join(d, "in.db1"); ifc = os.path.join(d, "model.ifc"); stp = os.path.join(d, "model.stp")
    stats = os.path.join(d, "convert.json"); logf = os.path.join(d, "log.txt")
    rec = {"sha": jid, "key": job["key"], "engine": job["engine"], "old_status": job["status"], "db1_bytes": job["bytes"],
           "host": HOST, "code": CODE, "writer": WRITER, "started": now(), "out_key": f"{OUT}/{jid}.stp",
           "pipeline": "db1dec+db1step -> ifc2step5.py --mode hybrid --prec 2"}
    try: prev = json.loads(s3.get_object(Bucket=B, Key=f"{ST}/results/{jid}.json")["Body"].read())
    except Exception: prev = None
    recheck = bool(prev and prev.get("status") == "ok" and prev.get("code") in (CODE, "db1-2026-09-25f") and not prev.get("arc_writer"))
    stop = threading.Event()
    threading.Thread(target=lambda: [touch(jid) for _ in iter(lambda: stop.wait(300), True)], daemon=True).start()
    try:
        s3.download_file(B, job["key"], db1)
        lay = layouts.get(job["engine"], {}).get("layout")
        lp = os.path.join(d, "layout.json"); json.dump(lay, open(lp, "w"))
        vp = os.path.join(d, "variants.json")
        json.dump([v["layout"] for v in layouts.values() if v.get("layout")], open(vp, "w"))
        t = time.time()
        rc = run(jid, [PY, os.path.join(WORK, "src", "convert_one.py"), db1, ifc, os.path.join(WORK, "tekla_profiles.json"), lp, stats, vp], logf, TIMEOUT)
        rec["convert_rc"] = rc; rec["convert_sec"] = round(time.time() - t, 1)
        if jid in KILLED or rc in (-9, 137): raise MemoryError("killed")
        cs = json.load(open(stats)) if os.path.exists(stats) else {}
        rec["convert"] = {k: v for k, v in cs.items() if k != "layout"}; rec["layout"] = cs.get("layout")
        rec["arc_writer"] = cs.get("arc_writer"); rec["arc_stats"] = cs.get("arc_stats")
        if (recheck and rc == 0 and cs.get("status") == "ok" and cs.get("arc_writer") == "arc2"
                and (cs.get("arc_stats") or {}).get("changed", 1) == 0
                and cs.get("written") == (prev.get("convert") or {}).get("written")):
            # every plate outline is identical under the fixed arc code: the published STEP stays as it is
            keep = dict(prev); keep.update(arc_writer="arc2", arc_check="unchanged", arc_stats=cs.get("arc_stats"),
                                           arc_checked_at=now(), arc_checked_by=HOST, arc_check_sec=rec["convert_sec"])
            put(f"{ST}/results/{jid}.json", keep)
            return keep
        if recheck: rec["arc_check"] = "rewritten"
        if rc != 0 or cs.get("status") != "ok":
            rec["status"] = cs.get("status") or ("convert_timeout" if rc == 124 else "convert_fail")
            rec["log_tail"] = open(logf, errors="replace").read()[-2500:]
        else:
            t = time.time()
            # the converter's tessellator defaults to one thread per core IN EVERY JOB; with ~60 jobs per
            # host that oversubscription hung runs past 3 h that finish in seconds on a quiet machine
            step_py = PY84 if os.path.exists(PY84) else PY
            rec["step_ifcopenshell"] = "0.8.4.post1" if step_py == PY84 else "env-default"
            rc = run(jid, [step_py, os.path.join(WORK, "ifc2step5.py"), ifc, stp, "--mode", "hybrid", "--prec", "2", "--threads", "4"], logf, STEP_TIMEOUT, stall=1800)
            rec["step_rc"] = rc; rec["step_sec"] = round(time.time() - t, 1)
            if jid in KILLED or rc in (-9, 137): raise MemoryError("killed")
            if rc in (-11, 139, 124, 125) and os.path.exists(ifc):
                # the geometry kernel crashed on some element(s): find them by bisection, leave exactly those out
                rec["rescue"] = crash_rescue(jid, ifc, stp, logf, step_py, d)
                rc = rec["rescue"].get("rc", rc); rec["step_rc"] = rc
                if rec["rescue"].get("excluded"): rec["excluded_elements"] = rec["rescue"]["excluded"]
            if os.path.exists(stp + ".stats.json"):
                try: rec["step_stats"] = json.load(open(stp + ".stats.json"))
                except Exception: pass
            if rc != 0 or not os.path.exists(stp) or os.path.getsize(stp) == 0:
                rec["status"] = "step_fail"; rec["log_tail"] = open(logf, errors="replace").read()[-2500:]
            else:
                n = os.path.getsize(stp); rec["out_bytes"] = n
                m = {k.decode().rstrip("("): v for k, v in count(stp, [b"FACETED_BREP(", b"CLOSED_SHELL(", b"ADVANCED_FACE", b"TESSELLATED", b"TRIANGULATED_FACE_SET"]).items()}
                rec["markers"] = m
                head = open(stp, errors="replace").read(4000)
                rec["flavour_ok"] = (m["ADVANCED_FACE"] == 0 and m["TESSELLATED"] == 0 and m["TRIANGULATED_FACE_SET"] == 0 and "AUTOMOTIVE_DESIGN" in head)
                geom = {}
                if n < RB_MAX:
                    try:
                        v = subprocess.run([PY, os.path.join(WORK, "validate_step.py"), stp], capture_output=True, text=True, timeout=1800).stdout
                        geom = json.loads(v.strip().splitlines()[-1])
                    except Exception as e:
                        geom = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
                else:
                    geom = {"skipped": "output >= 64 MB"}
                rec["readback"] = geom
                solids = geom.get("solids") if geom.get("read_status") == "ok" else m["FACETED_BREP"]
                rec["grade"] = "ok_solid" if (solids or 0) > 0 else "empty"
                rec["status"] = "ok" if rec["grade"] == "ok_solid" and rec["flavour_ok"] else "bad_output"
                if rec["status"] == "ok":
                    s3.upload_file(stp, B, rec["out_key"], ExtraArgs={"ContentType": "application/step"})
    except MemoryError:
        total, _ = mem()
        put(f"{ST}/deferred/{jid}.json", {"sha": jid, "host": HOST, "rss_at_kill_gb": NEED.get(jid, 0) >> 30,
                                          "min_mem_gb": (int(max(NEED.get(jid, 0) * 1.6, 8 << 30)) >> 30) + 8, "at": now()})
        try: s3.delete_object(Bucket=B, Key=f"{ST}/claims/{jid}.json")
        except Exception: pass
        rec["status"] = "deferred_memory"
    except Exception as e:
        rec["status"] = "worker_error"; rec["error"] = f"{type(e).__name__}: {str(e)[:300]}"; rec["trace"] = traceback.format_exc()[-1500:]
    finally:
        stop.set()
        subprocess.run(["rm", "-rf", d])
    rec["finished"] = now()
    if rec["status"] not in ("ok", "deferred_memory"):
        # an older code version may have published a STEP for this file: withdraw it
        try: s3.delete_object(Bucket=B, Key=rec["out_key"])
        except Exception: pass
    if rec["status"] != "deferred_memory":
        put(f"{ST}/results/{jid}.json", rec)
    return rec


def rss_of(pid):
    tot = 0
    try: pids = [pid] + [int(x) for x in open(f"/proc/{pid}/task/{pid}/children").read().split()]
    except Exception: pids = [pid]
    for q in pids:
        try:
            for ln in open(f"/proc/{q}/status"):
                if ln.startswith("VmRSS:"): tot += int(ln.split()[1]) * 1024
        except Exception: pass
    return tot


def main():
    setup_env()
    jobs = json.loads(s3.get_object(Bucket=B, Key=f"{CTL}/db1_jobs.json")["Body"].read())["jobs"]
    layouts = json.loads(s3.get_object(Bucket=B, Key=f"{CTL}/layouts.json")["Body"].read())
    approved = {e for e, v in layouts.items() if v.get("approved")}
    only = set(filter(None, os.environ.get("DB1_ENGINES", "").split(",")))
    todo = not_done([j for j in jobs if j["engine"] in approved and (not only or j["engine"] in only)])
    done = set(j["sha"] for j in jobs) - set(j["sha"] for j in todo)
    todo.sort(key=lambda j: j["bytes"] if os.environ.get("DB1_ORDER") == "small" else -j["bytes"])
    total, _ = mem()
    log(f"code={CODE} host={HOST} slots={SLOTS} mem={total>>30}GB approved={sorted(approved)} todo={len(todo)} done={len(done)}")
    running = {}; lock = threading.Lock(); stats = {"ok": 0, "other": 0}

    def beat():
        while True:
            try:
                t, a = mem()
                with lock: snap = {"host": HOST, "code": CODE, "at": now(), "running": list(running), "stats": dict(stats), "mem_total_gb": t >> 30, "mem_avail_gb": a >> 30}
                put(f"{ST}/hosts/{HOST}.json", snap)
                with LOGLOCK: s3.put_object(Bucket=B, Key=f"{ST}/logs/{HOST}.log", Body="\n".join(LOGBUF).encode())
            except Exception: pass
            time.sleep(60)
    threading.Thread(target=beat, daemon=True).start()

    def watchdog():
        while True:
            try:
                t, a = mem()
                if a < max(6 << 30, int(t * 0.07)):
                    with PLOCK: cand = [(rss_of(p.pid), jid, p) for jid, (p, st) in PROCS.items()]
                    if cand:
                        r, jid, p = max(cand); NEED[jid] = r; KILLED.add(jid)
                        subprocess.run(["pkill", "-9", "-P", str(p.pid)], capture_output=True); p.kill()
                        log(f"WATCHDOG killed {jid[:12]} rss={r>>30}GB avail={a>>30}GB -> deferred")
                        time.sleep(8)
            except Exception: pass
            time.sleep(1)
    threading.Thread(target=watchdog, daemon=True).start()

    def work(job):
        try:
            r = process(job, layouts)
            with lock: stats["ok" if r["status"] == "ok" else "other"] += 1
            log(f"{r['status']:>22} {job['engine']} {job['bytes']>>20:>5}MB {r.get('convert_sec','?')}s+{r.get('step_sec','?')}s "
                f"members={r.get('convert',{}).get('members')} written={r.get('convert',{}).get('written')} {job['sha'][:12]}")
        finally:
            with lock: running.pop(job["sha"], None)

    reserved = {}
    def need_of(job, dj=None):
        n = max(2 << 30, int(job["bytes"] * 30))          # measured: ~4 GB RSS at 185 MB gz early in decode
        if dj: n = max(n, dj.get("min_mem_gb", 0) << 30)
        return min(n, int(total * 0.7))
    for rnd in range(1, 6):
        pending = not_done(todo)
        log(f"round {rnd}: {len(pending)} pending")
        if not pending: break
        for job in pending:
            dj = None
            try:
                dj = json.loads(s3.get_object(Bucket=B, Key=f"{ST}/deferred/{job['sha']}.json")["Body"].read())
                if (total >> 30) * 0.8 < dj.get("min_mem_gb", 0): continue
            except ClientError: pass
            n = need_of(job, dj)
            while True:
                with lock: busy = len(running); res = sum(reserved.get(k, 0) for k in running)
                t, a = mem()
                if busy < SLOTS and (busy == 0 or (res + n < t * 0.8 and a > n + (8 << 30))): break
                time.sleep(2)
            if done_now(job["sha"]) or not claim(job["sha"]): continue
            with lock: running[job["sha"]] = job["bytes"]; reserved[job["sha"]] = n
            threading.Thread(target=work, args=(job,), daemon=True).start()
        while running: time.sleep(10)
        time.sleep(30)
    left = not_done(todo)
    # idle hook: nothing left to claim here -> lend this host to the IFC finishing work (claim-based,
    # runs until no IFC job is open). Only while the hold flag keeps the fleet alive.
    if exists(f"{CTL}/hold"):
        try:
            hook = os.path.join(WORK, "idle_hook.py")
            s3.download_file(B, f"{CTL}/idle_hook.py", hook)
            log("running idle hook (IFC finishing)")
            subprocess.run([sys.executable, hook], env=dict(os.environ, W=WORK), timeout=12 * 3600,
                           stdout=open(os.path.join(WORK, "idle_hook.log"), "a"), stderr=subprocess.STDOUT)
            log("idle hook finished")
        except ClientError:
            pass
        except Exception as e:
            log(f"idle hook error: {type(e).__name__}: {str(e)[:200]}")
    if not left and exists(f"{CTL}/hold"):
        log("all jobs done on this code but the hold flag is set: not finishing (restart)")
    elif not left:
        open(os.path.join(WORK, "DONE"), "w").write(now())
        log("ALL DB1 JOBS DONE")
    else:
        log(f"{len(left)} jobs still unfinished (claimed elsewhere / deferred); exiting for restart")
    time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("FATAL " + traceback.format_exc())
        try:
            put(f"{ST}/hosts/{HOST}.fatal.json", {"at": now(), "trace": traceback.format_exc()})
            with LOGLOCK: s3.put_object(Bucket=B, Key=f"{ST}/logs/{HOST}.log", Body="\n".join(LOGBUF).encode())
        except Exception: pass
        raise
