"""Refresh packaged STEP copies whose conversion output was rewritten after the copy was made
(DB1 arc2 rewrites, repaired IFC conversions). Uses the packaging plans as the list of placements.
A copy is stale when its source conversion object is newer than the copy, or the sizes differ.
Stale copies are re-copied (pkg_step's copy: multipart above 1 GB), and the project's manifest rows
(bytes, etag, converter) and project.json totals (files, bytes) are updated exactly as pkg_step writes them.
  refresh_packaged.py            -> dry run
  refresh_packaged.py --apply    -> apply; writes _control/packaging/refresh/report.json
Run only when no packaging pass is touching the same projects (after the end-game)."""
import collections, json, os, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
os.environ.setdefault("AWS_PROFILE", "bim")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pkg_step as P   # s3(), copy(), get_json(), list_keys(), DEST, B, R

APPLY = "--apply" in sys.argv
B, R, DEST = P.B, P.R, P.DEST
PLANS = [f"{R}/_control/packaging/step_v1_ifc/plan.json", f"{R}/_control/packaging/step_v1_ifc2/plan.json",
         f"{R}/_control/packaging/step_v1_db1/plan.json", f"{R}/_control/packaging/step_v1_db1_posthoc/plan.json",
         f"{R}/_control/packaging/step_v1_db1_posthoc2/plan.json"]
place = []
for k in PLANS:
    pl = P.get_json(k) or []
    for p in pl:
        for a in p.get("adds") or []:
            place.append((p["project"], a["name"], a["out_key"]))
print("placements in plans:", len(place), flush=True)

def check(t):
    proj, name, src = t
    dst = f"{DEST}/3d/{proj}/model/step/{name}"
    try:
        hs = P.s3().head_object(Bucket=B, Key=src); hd = P.s3().head_object(Bucket=B, Key=dst)
    except Exception as e:
        return (t, "missing", str(e)[:80])
    stale = hs["LastModified"] > hd["LastModified"] or hs["ContentLength"] != hd["ContentLength"]
    return (t, "stale" if stale else "fresh", (hs["ContentLength"], hd["ContentLength"]))

with ThreadPoolExecutor(64) as ex: res = list(ex.map(check, place))
st = collections.Counter(r[1] for r in res)
print("status:", dict(st), flush=True)
missing = [r for r in res if r[1] == "missing"]
for m in missing[:10]: print("  missing:", m[0][0][:60], m[0][1], m[2], flush=True)
stale = [r[0] for r in res if r[1] == "stale"]
by_proj = collections.defaultdict(list)
for proj, name, src in stale: by_proj[proj].append((name, src))
print("stale copies:", len(stale), "in", len(by_proj), "projects", flush=True)
if not APPLY: sys.exit(0)

def conv_label(src):
    key = src.rsplit("/", 1)[1][:-4]
    if "/conversions/db1-step/" in src:
        r = P.get_json(f"{R}/_state/db1-v2/results/{key}.json") or {}
        return "db1dec+db1step (" + str(r.get("code", "")) + ") -> ifc2step5.py --mode hybrid --prec 2"
    r = P.get_json(f"{R}/_state/ifc-step/results/{key}.json") or {}
    lab = r.get("converter") or "ifc2step5.py --mode hybrid --prec 2"
    fx = r.get("input_unzipped") or r.get("input_fix")
    return lab + (f" [input: {fx}]" if fx and fx != "none" else "")

done = collections.Counter(); errors = []
def one(proj):
    pre = f"{DEST}/3d/{proj}/"
    items = by_proj[proj]
    for name, src in items:
        P.copy(src, pre + "model/step/" + name, P.s3().head_object(Bucket=B, Key=src)["ContentLength"])
    rows = [json.loads(l) for l in P.s3().get_object(Bucket=B, Key=pre + "manifest.jsonl")["Body"].read().decode().splitlines() if l.strip()]
    idx = {r["relpath"]: r for r in rows}
    for name, src in items:
        r = idx.get("model/step/" + name)
        if r is None: raise RuntimeError(f"row missing for {name}")
        h = P.s3().head_object(Bucket=B, Key=pre + "model/step/" + name)
        r["bytes"] = h["ContentLength"]; r["etag"] = h["ETag"].strip('"'); r["converter"] = conv_label(src)
        r["refreshed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    P.s3().put_object(Bucket=B, Key=pre + "manifest.jsonl", Body="\n".join(json.dumps(r) for r in rows).encode(), ContentType="application/x-ndjson")
    pj = P.get_json(pre + "project.json") or {}
    pj["files"] = len(rows); pj["bytes"] = sum(int(r.get("bytes") or 0) for r in rows)
    P.s3().put_object(Bucket=B, Key=pre + "project.json", Body=json.dumps(pj, indent=1).encode(), ContentType="application/json")
    return len(items)

def safe(proj):
    try: n = one(proj); done["projects"] += 1; done["copies"] += n
    except Exception as e: errors.append((proj, f"{type(e).__name__}: {str(e)[:200]}"))
with ThreadPoolExecutor(16) as ex: list(ex.map(safe, sorted(by_proj)))
rep = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "placements": len(place), "status": dict(st),
       "refreshed": dict(done), "errors": errors[:50], "missing": [[m[0][0], m[0][1], m[2]] for m in missing[:200]]}
P.s3().put_object(Bucket=B, Key=f"{R}/_control/packaging/refresh/report.json", Body=json.dumps(rep, indent=1).encode())
print("REFRESH DONE", json.dumps({k: rep[k] for k in ("status", "refreshed")}), "errors", len(errors), flush=True)
if errors: sys.exit(3)
