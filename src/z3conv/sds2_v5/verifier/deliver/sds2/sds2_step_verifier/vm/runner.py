"""Mass calibration run: fetch -> pre-check -> stage-1 convert+verify -> stage-2 convert+verify, in parallel.

usage: python runner.py manifest.csv <root> [workers] [stage2_max_members]
manifest.csv: id, version, name, members, archive, job_root, jobs_in_archive, url
Layout under <root>: work/<id>/ (extracted job, deleted after), out/<id>/ (STEPs, logs, verify reports),
cache/ (downloaded 7z archives), results.jsonl (one line per job, appended; resumable).
Every step runs in its own process with a timeout, so one bad job cannot take the run down.
"""
import os, sys, csv, json, time, shutil, subprocess, traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
DECODE = os.path.join(HERE, "decode"); VERIFY = os.path.join(HERE, "verify")


def run(cmd, log, timeout):
    t0 = time.time()
    with open(log, "w", encoding="utf-8", errors="replace") as f:
        try:
            p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout, cwd=os.path.dirname(cmd[1]))
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    return rc, round(time.time() - t0, 1)


def load_report(prefix):
    try:
        return json.load(open(prefix + ".json", encoding="utf-8"))
    except Exception:
        return None


def one(row, root, s2max):
    sys.path.insert(0, HERE)
    from fetch import fetch
    jid = row["id"]; out = os.path.join(root, "out", jid); work = os.path.join(root, "work", jid)
    os.makedirs(out, exist_ok=True)
    res = dict(id=jid, version=row["version"], name=row["name"], members_listed=int(row["members"]), archive=row["archive"], steps={})
    try:
        info = fetch(row["url"], row["archive"], row["job_root"], work, os.path.join(root, "cache"), row.get("jobs_in_archive", 1))
        res["fetch"] = info
        job = info["jobdir"]
        if not os.path.isdir(os.path.join(job, "mem")):
            res["error"] = "job folder missing mem/ after extraction"; return res
        gt = ["--gt", info["gt_dir"]] if info["gt_dir"] else []
        # 1. pre-conversion gate
        pre = os.path.join(out, "precheck")
        rc, s = run([PY, os.path.join(VERIFY, "verify.py"), "--job", job, "--out", pre], os.path.join(out, "precheck.log"), 1800)
        rep = load_report(pre); res["steps"]["precheck"] = dict(rc=rc, s=s, overall=rep and rep["overall"],
                                                               checks={c["id"]: c["status"] for c in rep["checks"]} if rep else None)
        d1 = next((c for c in (rep or {}).get("checks", []) if c["id"] == "D1"), None)
        res["layout"] = d1 and d1["metrics"]
        if not rep or (d1 and d1["status"] == "FAIL"):
            return res
        # 2. stage 1
        st1 = os.path.join(out, "stage1.step")
        rc, s = run([PY, os.path.join(DECODE, "to_step.py"), job, st1], os.path.join(out, "stage1_convert.log"), 7200)
        res["steps"]["stage1_convert"] = dict(rc=rc, s=s, step_bytes=os.path.getsize(st1) if os.path.exists(st1) else 0)
        if os.path.exists(st1):
            rc, s = run([PY, os.path.join(VERIFY, "verify.py"), "--job", job, "--step", st1, "--selftest"] + gt,
                        os.path.join(out, "stage1_verify.log"), 10800)
            rep = load_report(os.path.join(out, "stage1_verify"))
            res["steps"]["stage1_verify"] = dict(rc=rc, s=s, report=rep)
        # 3. stage 2 (fabricated pieces)
        if int(row["members"]) <= s2max:
            st2 = os.path.join(out, "stage2.step")
            rc, s = run([PY, os.path.join(DECODE, "to_step2.py"), job, st2], os.path.join(out, "stage2_convert.log"), 14400)
            res["steps"]["stage2_convert"] = dict(rc=rc, s=s, step_bytes=os.path.getsize(st2) if os.path.exists(st2) else 0)
            if os.path.exists(st2):
                rc, s = run([PY, os.path.join(VERIFY, "verify.py"), "--job", job, "--step", st2, "--selftest"] + gt,
                            os.path.join(out, "stage2_verify.log"), 21600)
                rep = load_report(os.path.join(out, "stage2_verify"))
                res["steps"]["stage2_verify"] = dict(rc=rc, s=s, report=rep)
    except Exception as ex:
        res["error"] = f"{type(ex).__name__}: {ex}"; res["trace"] = traceback.format_exc()[-2000:]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return res


def main():
    man, root = sys.argv[1], sys.argv[2]
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 14
    s2max = int(sys.argv[4]) if len(sys.argv) > 4 else 10000
    rows = list(csv.DictReader(open(man, encoding="utf-8-sig")))
    resf = os.path.join(root, "results.jsonl")
    done = set()
    if os.path.exists(resf):
        done = {json.loads(l)["id"] for l in open(resf, encoding="utf-8") if l.strip()}
    todo = [r for r in rows if r["id"] not in done]
    todo.sort(key=lambda r: -int(r["members"]))          # big jobs first so they do not trail at the end
    os.makedirs(os.path.join(root, "cache"), exist_ok=True)
    print(f"{len(todo)} jobs to run ({len(done)} done), {workers} workers", flush=True)
    with ProcessPoolExecutor(workers) as ex, open(resf, "a", encoding="utf-8") as fo:
        futs = {ex.submit(one, r, root, s2max): r["id"] for r in todo}
        for fu in as_completed(futs):
            try:
                res = fu.result()
            except Exception as e:
                res = dict(id=futs[fu], error=f"worker crashed: {e}")
            fo.write(json.dumps(res, default=str) + "\n"); fo.flush()
            st = {k: (v.get("report") or {}).get("overall") if isinstance(v, dict) and "report" in v else (v.get("overall") if isinstance(v, dict) else v) for k, v in res.get("steps", {}).items()}
            print(time.strftime("%H:%M:%S"), res["id"], res.get("version"), res.get("error") or st, flush=True)
    print("all done", flush=True)


if __name__ == "__main__":
    main()
