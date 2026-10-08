#!/usr/bin/env python3
"""Collapse byte-identical STEP files inside one project (projpkg4 rule: within a project a (channel, etag,
size) content appears once). Conversions can produce identical STEP from different sources (two dated IFC
exports of the same model, conflicted copies of one DB1); the packager's content dedup ran before the
conversions were added, so these were never collapsed.

Per duplicate group (same etag+bytes under model/step/):
  keep  : a native STEP if one is in the group, else the smallest relpath
  drop  : the other rows; their objects are deleted
  kept row gains "also_converted_from": [converted_from of every dropped conversion row]
          (the dropped sources keep a STEP, through the kept file)
project.json: files, bytes, slots.model_step, model_formats.step, model_step_by_source,
conversions.<src>.step_added (recounted from the manifest), duplicates_collapsed (+n),
step_duplicates_collapsed (+n)

  dedup_step.py plan            -> report only (_control/packaging/dedup_step/plan.json)
  dedup_step.py apply           -> apply the saved plan (idempotent per project)
DEDUP_SHARD=i/N optional."""
import collections, json, os, sys, time, zlib, threading
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

B = "annotationprod"; R = "cad-disk-extract"; DEST = f"{R}/dataset/main"; OUT = f"{R}/_control/packaging/dedup_step"
TL = threading.local(); L = threading.Lock(); SESS = boto3.Session()


def s3():
    c = getattr(TL, "c", None)
    if c is None:
        with L:
            c = SESS.client("s3", region_name="ap-south-1", config=Config(max_pool_connections=64, retries={"max_attempts": 10, "mode": "standard"},
                                                                         connect_timeout=30, read_timeout=300))
        TL.c = c
    return c


def src_of(r):
    cf = r.get("converted_from") or ""
    if cf.startswith("model/db1/"): return "db1"
    if cf.startswith("model/ifc/"): return "ifc"
    sk = r.get("source_key") or ""
    if "/derived/db1-step/" in sk or "/conversions/db1-step/" in sk: return "db1"
    if "/conversions/ifc-step/" in sk or "/derived/ifc-step/" in sk: return "ifc"
    return "native"


def rows_of(pre):
    return [json.loads(l) for l in s3().get_object(Bucket=B, Key=pre + "manifest.jsonl")["Body"].read().decode().splitlines() if l.strip()]


def groups(rows):
    g = collections.defaultdict(list)
    for r in rows:
        if r["relpath"].startswith("model/step/") and (r.get("etag") or ""):
            g[((r.get("etag") or "").strip('"'), r.get("bytes"))].append(r)
    out = []
    for (et, by), rs in g.items():
        if len(rs) < 2: continue
        nat = sorted((r for r in rs if src_of(r) == "native"), key=lambda r: r["relpath"])
        keep = nat[0] if nat else sorted(rs, key=lambda r: r["relpath"])[0]
        drop = [r for r in rs if r is not keep]
        out.append({"etag": et, "bytes": by, "keep": keep["relpath"], "drop": [r["relpath"] for r in drop],
                    "drop_sources": [r.get("converted_from") for r in drop], "kinds": sorted({src_of(r) for r in rs})})
    return out


def plan_one(pre):
    try: rows = rows_of(pre)
    except ClientError: return None          # empty package (0 files): no manifest
    gs = groups(rows)
    return {"project": pre.split("/")[-2], "prefix": pre, "groups": gs} if gs else None


def apply_one(p):
    pre = p["prefix"]; done = f"{OUT}/done/{p['project']}.json"
    try: s3().head_object(Bucket=B, Key=done); return "skip"
    except ClientError: pass
    rows = rows_of(pre); idx = {r["relpath"]: r for r in rows}
    dropped = set()
    for g in p["groups"]:
        keep = idx.get(g["keep"])
        if keep is None: raise RuntimeError(f"kept row missing: {g['keep']}")
        for rel in g["drop"]:
            r = idx.get(rel)
            if r is None: continue                   # already collapsed by an earlier (interrupted) run
            if (r.get("etag") or "").strip('"') != g["etag"] or r.get("bytes") != g["bytes"]:
                raise RuntimeError(f"row changed since plan: {rel}")
            cf = r.get("converted_from")
            if cf:
                also = keep.setdefault("also_converted_from", [])
                if cf not in also: also.append(cf)
            dropped.add(rel)
    rows = [r for r in rows if r["relpath"] not in dropped]
    # manifest first (never a row without its object), then remove the objects
    s3().put_object(Bucket=B, Key=pre + "manifest.jsonl", Body="\n".join(json.dumps(r) for r in rows).encode(), ContentType="application/x-ndjson")
    keys = [pre + rel for rel in sorted(dropped)]
    for i in range(0, len(keys), 1000):
        s3().delete_objects(Bucket=B, Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]]})
    pj = json.loads(s3().get_object(Bucket=B, Key=pre + "project.json")["Body"].read())
    steps = [r for r in rows if r["relpath"].startswith("model/step/")]
    pj.setdefault("slots", {})["model_step"] = len(steps)
    pj.setdefault("model_formats", {})["step"] = len(steps)
    pj["model_step_by_source"] = dict(collections.Counter(r.get("step_source") or src_of(r) for r in steps))
    conv = pj.get("conversions") or {}
    for k in ("ifc", "db1"):
        if k in conv and isinstance(conv[k], dict):
            conv[k]["step_added"] = sum(1 for r in steps if src_of(r) == k)
    pj["conversions"] = conv
    pj["files"] = len(rows); pj["bytes"] = sum(int(r.get("bytes") or 0) for r in rows)
    pj["duplicates_collapsed"] = int(pj.get("duplicates_collapsed") or 0) + len(dropped)
    pj["step_duplicates_collapsed"] = int(pj.get("step_duplicates_collapsed") or 0) + len(dropped)
    s3().put_object(Bucket=B, Key=pre + "project.json", Body=json.dumps(pj, indent=1).encode(), ContentType="application/json")
    s3().put_object(Bucket=B, Key=done, Body=json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dropped": sorted(dropped)}).encode())
    return "collapsed"


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if mode == "plan":
        pres = [p["Prefix"] for pg in s3().get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=f"{DEST}/3d/", Delimiter="/") for p in pg.get("CommonPrefixes", [])]
        sh = os.environ.get("DEDUP_SHARD")
        if sh:
            i, n = (int(x) for x in sh.split("/")); pres = [p for p in pres if zlib.crc32(p.encode()) % n == i]
        with ThreadPoolExecutor(24) as ex: plan = [x for x in ex.map(plan_one, pres) if x]
        name = "plan.json" if not sh else f"plan_{sh.replace('/', '_of_')}.json"
        s3().put_object(Bucket=B, Key=f"{OUT}/{name}", Body=json.dumps(plan).encode())
        kinds = collections.Counter(k for p in plan for g in p["groups"] for k in g["kinds"])
        print(json.dumps({"projects_checked": len(pres), "projects_with_dups": len(plan), "groups": sum(len(p["groups"]) for p in plan),
                          "rows_to_drop": sum(len(g["drop"]) for p in plan for g in p["groups"]), "kinds": dict(kinds)}), flush=True)
        return
    plan = json.loads(s3().get_object(Bucket=B, Key=f"{OUT}/plan.json")["Body"].read())
    st = collections.Counter(); errs = []
    def safe(p):
        try: st[apply_one(p)] += 1
        except Exception as e: errs.append((p["project"], f"{type(e).__name__}: {str(e)[:200]}"))
    with ThreadPoolExecutor(8) as ex: list(ex.map(safe, plan))
    print("DEDUP DONE", dict(st), "errors", errs[:10], flush=True)
    if errs: sys.exit(3)


if __name__ == "__main__":
    main()
