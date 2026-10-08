"""End-game conditions and markers (runs on a packaging box with its instance role, or locally).
  endgame.py status          -> print conditions
  endgame.py wait <cond>     -> block until cond true: db1_final | ifc_final | marker:<name> | markers:<a>,<b>
  endgame.py mark <name>     -> write marker _control/packaging/endgame/<name>
  endgame.py release_fleet   -> delete the DB1 hold flag (fleet hosts then write DONE and terminate)"""
import json, sys, time, boto3
from concurrent.futures import ThreadPoolExecutor
B = "annotationprod"; R = "cad-disk-extract"; EG = f"{R}/_control/packaging/endgame"
s3 = boto3.client("s3", region_name="ap-south-1")
FINAL_CODE = "db1-2026-09-25g"
KEEP_NONOK = {"empty_model", "no_member_layout", "no_resolvable_members", "bad_output", "deferred_layout"}
OLD = ("db1-2026-09-25b", "db1-2026-09-25c", "db1-2026-09-25d", "db1-2026-09-25e")
F_KEEP = {"ok", "empty_model", "no_member_layout", "no_resolvable_members", "bad_output", "deferred_layout", "suspect_orientation", "suspect_attr_link", "convert_error"}
def keys(pre):
    return [o["Key"] for pg in s3.get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=pre) for o in pg.get("Contents", [])]
def getj(k):
    for _ in range(3):
        try: return json.loads(s3.get_object(Bucket=B, Key=k)["Body"].read())
        except s3.exceptions.NoSuchKey: return None
        except Exception: time.sleep(1)
def db1_state():
    jobs = [j for j in json.loads(s3.get_object(Bucket=B, Key=f"{R}/_control/db1-v2/db1_jobs.json")["Body"].read())["jobs"] if j["engine"] != "None"]
    with ThreadPoolExecutor(64) as ex: rs = list(ex.map(lambda j: getj(f"{R}/_state/db1-v2/results/{j['sha']}.json"), jobs))
    fin = sum(1 for r in rs if r and (r.get("code") == FINAL_CODE or (r.get("code") == "db1-2026-09-25f" and r.get("status") in F_KEEP) or (r.get("code") in OLD and r.get("status") in KEEP_NONOK)))
    return fin, len(jobs)
def ifc_state():
    jobs = json.loads(s3.get_object(Bucket=B, Key=f"{R}/_control/ifc-step/ifc_jobs.json")["Body"].read()); jobs = jobs["jobs"] if isinstance(jobs, dict) else jobs
    with ThreadPoolExecutor(64) as ex: rs = list(ex.map(lambda j: getj(f"{R}/_state/ifc-step/results/{j['id']}.json"), jobs))
    open_ids = [j["id"] for j, r in zip(jobs, rs) if r is None or (r.get("status") not in ("ok", "empty") and not r.get("finisher"))]
    # fresh finisher claims (touched < 15 min ago) = work in progress; stale leftovers of the old IFC fleet do not count
    fresh = 0; stuck = 0
    for jid in open_ids:
        try: age = time.time() - s3.head_object(Bucket=B, Key=f"{R}/_state/ifc-step/claims/{jid}.json")["LastModified"].timestamp()
        except Exception: age = None
        if age is not None and age < 900: fresh += 1
        d = getj(f"{R}/_state/ifc-step/deferred/{jid}.json")
        if d and d.get("by") == "ifc_finish": stuck += 1      # even a 512 GB host could not hold it
    return len(open_ids), fresh, stuck, len(jobs)
def has(name): return getj(f"{EG}/{name}") is not None or bool(keys(f"{EG}/{name}"))
def cond(c):
    if c == "db1_final": f, n = db1_state(); return f >= n
    if c == "ifc_final":
        o, fresh, stuck, n = ifc_state()
        return o == 0 or (fresh == 0 and stuck == o)
    if c.startswith("marker:"): return bool(keys(f"{EG}/{c[7:]}"))
    if c.startswith("markers:"): return all(keys(f"{EG}/{x}") for x in c[8:].split(","))
    raise SystemExit("bad cond " + c)
if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "status":
        f, n = db1_state(); o, fresh, stuck, m = ifc_state()
        print(json.dumps({"db1_final": f, "db1_jobs": n, "ifc_open": o, "ifc_in_progress": fresh, "ifc_memory_stuck": stuck, "ifc_jobs": m, "markers": [k.rsplit("/", 1)[1] for k in keys(EG + "/")]}))
    elif cmd == "wait":
        while True:
            try:
                if cond(sys.argv[2]): break
            except Exception as e:      # a transient S3 error must never read as "condition met"
                print(time.strftime("%H:%M:%SZ", time.gmtime()), "check error, retrying:", type(e).__name__, flush=True)
            time.sleep(120)
        print(time.strftime("%H:%M:%SZ", time.gmtime()), "condition met:", sys.argv[2], flush=True)
    elif cmd == "mark":
        s3.put_object(Bucket=B, Key=f"{EG}/{sys.argv[2]}", Body=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()).encode())
    elif cmd == "release_fleet":
        s3.delete_object(Bucket=B, Key=f"{R}/_control/db1-v2/hold"); print("hold removed", flush=True)
