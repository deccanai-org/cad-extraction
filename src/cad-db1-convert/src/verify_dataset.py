"""Full structural verification of dataset/main/{3d,2d} after packaging.  VERIFY_SHARD=i/N optional.
Writes _control/packaging/verify/<shard>.json with per-check counts + up to 50 examples each."""
import json, os, sys, time, zlib, collections, threading, boto3
from concurrent.futures import ThreadPoolExecutor
from botocore.config import Config
B = "annotationprod"; D = "cad-disk-extract/dataset/main"; OUT = os.environ.get("VERIFY_OUT", "cad-disk-extract/_control/packaging/verify")
TL = threading.local(); SESS = boto3.Session(); L = threading.Lock()
def s3():
    c = getattr(TL, "c", None)
    if c is None:
        with L: c = SESS.client("s3", region_name="ap-south-1", config=Config(max_pool_connections=64, retries={"max_attempts": 10, "mode": "standard"}, connect_timeout=30, read_timeout=300))
        TL.c = c
    return c
def prefixes(route):
    return [p["Prefix"] for pg in s3().get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=f"{D}/{route}/", Delimiter="/") for p in pg.get("CommonPrefixes", [])]
p3, p2 = prefixes("3d"), prefixes("2d")
n3 = {p.split("/")[-2] for p in p3}; n2 = {p.split("/")[-2] for p in p2}
sh = os.environ.get("VERIFY_SHARD")
todo = [(r, p) for r, lst in (("3d", p3), ("2d", p2)) for p in lst]
if sh:
    i, n = (int(x) for x in sh.split("/")); todo = [t for t in todo if zlib.crc32(t[1].encode()) % n == i]
C = collections.Counter(); EX = collections.defaultdict(list)
def bad(k, ex):
    with L:
        C[k] += 1
        if len(EX[k]) < 50: EX[k].append(ex)
def one(t):
    route, pre = t; pid = pre.split("/")[-2]
    objs = {o["Key"][len(pre):]: o["Size"] for pg in s3().get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=pre) for o in pg.get("Contents", [])}
    try: man = [json.loads(l) for l in s3().get_object(Bucket=B, Key=pre + "manifest.jsonl")["Body"].read().decode().splitlines() if l.strip()]
    except Exception as e:
        # a package whose archive held only non-asset files has project.json (files 0) and nothing else
        try: pj0 = json.loads(s3().get_object(Bucket=B, Key=pre + "project.json")["Body"].read())
        except Exception: pj0 = None
        if pj0 is not None and int(pj0.get("files") or 0) == 0 and set(objs) <= {"project.json"}:
            bad("empty_packages", pid); return
        bad("manifest_unreadable", pid); return
    try: pj = json.loads(s3().get_object(Bucket=B, Key=pre + "project.json")["Body"].read())
    except Exception: bad("project_json_unreadable", pid); pj = {}
    rel = [r["relpath"] for r in man]; relset = set(rel)
    if len(rel) != len(relset): bad("duplicate_relpath_rows", pid)
    meta = {"manifest.jsonl", "project.json"}
    miss = relset - set(objs); extra = set(objs) - relset - meta
    if miss: bad("rows_without_object", (pid, sorted(miss)[:3]))
    if extra: bad("objects_without_row", (pid, sorted(extra)[:3]))
    steps = [r for r in man if r["relpath"].startswith("model/step/")]
    with L:
        C["projects_" + route] += 1; C["step_rows_" + route] += len(steps)
        for r in steps: C[f"step_source_{r.get('step_source', 'MISSING')}"] += 1
    if route == "2d" and steps: bad("step_in_2d", pid)
    if route == "3d" and not steps: bad("3d_without_step", pid)
    if pj.get("route") != route: bad("project_json_route_mismatch", (pid, pj.get("route")))
    if route == "3d" and (pj.get("slots") or {}).get("model_step") != len(steps): bad("slots_model_step_mismatch", (pid, (pj.get("slots") or {}).get("model_step"), len(steps)))
    if route == "3d" and pid in n2: bad("project_in_both_routes", pid)
    for r in steps:
        if "step_source" not in r: bad("step_row_without_source", pid); break
    for r in steps:
        cf = r.get("converted_from")
        if cf and cf not in relset: bad("converted_from_missing", (pid, cf)); break
    for r in man:
        if r["relpath"] in objs and r.get("bytes") is not None and int(r["bytes"]) != objs[r["relpath"]]:
            bad("bytes_mismatch", (pid, r["relpath"])); break
    # dedup, with the packager's own identity rule: inside one project a (channel, etag, size) content may
    # appear once; a conversion output (source_key) may be placed once
    grp = collections.Counter(); conv = collections.Counter()
    for r in man:
        et = (r.get("etag") or "").strip('"')
        ch = "/".join(r["relpath"].split("/")[:2])
        if et: grp[(ch, et, r.get("bytes"))] += 1
        if r["relpath"].startswith("model/step/") and r.get("converted_from") and r.get("source_key"): conv[r["source_key"]] += 1
    dup = sum(v - 1 for v in grp.values() if v > 1)
    stepdup = sum(v - 1 for k, v in grp.items() if v > 1 and k[0] == "model/step")
    convdup = sum(v - 1 for v in conv.values() if v > 1)
    with L:
        C["content_duplicate_rows"] += dup; C["step_content_duplicate_rows"] += stepdup; C["step_same_conversion_twice"] += convdup
    if dup: bad("projects_with_content_duplicates", (pid, dup))
    if convdup: bad("projects_with_conversion_placed_twice", (pid, convdup))
t0 = time.time()
with ThreadPoolExecutor(24) as ex: list(ex.map(one, todo))
res = {"shard": sh or "all", "projects_checked": len(todo), "secs": round(time.time() - t0), "counts": dict(C), "examples": {k: v for k, v in EX.items()}}
s3().put_object(Bucket=B, Key=f"{OUT}/{(sh or 'all').replace('/', '_of_')}.json", Body=json.dumps(res, default=str).encode())
print(json.dumps({k: v for k, v in res.items() if k != "examples"}), flush=True)
