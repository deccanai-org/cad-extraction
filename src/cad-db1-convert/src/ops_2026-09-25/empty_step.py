#!/usr/bin/env python3
"""Remove STEP files that hold no geometry from dataset/main/3d.

The original Windows DB1 pipeline wrote a header-only STEP (one PRODUCT with an empty
SHAPE_REPRESENTATION) for every DB1 it FAILED on ("no solids written"); the original packager copied those
into the packages as model/step. They are not models. A STEP row is removed only when BOTH hold:
  * its source is an old-pipeline output (derived/db1-step/...) whose result.json status is not OK, and
  * the file itself contains no geometry entity (no B-rep, shell, face, loop, edge, tessellation, or point
    other than the origin).
A project whose only STEP rows are removed moves back to main/2d (projpkg4: 3d = holds a STEP model).
Each project records removed_empty_step (+ the removed relpaths) in project.json.

  empty_step.py plan     -> _control/packaging/empty_step/plan.json (+ summary on stdout)
  empty_step.py apply    -> apply the saved plan (idempotent per project)"""
import collections, json, re, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

B = "annotationprod"; R = "cad-disk-extract"; DEST = f"{R}/dataset/main"; OUT = f"{R}/_control/packaging/empty_step"
TL = threading.local(); L = threading.Lock(); SESS = boto3.Session()
GEOM = re.compile(rb"(FACETED_BREP|MANIFOLD_SOLID_BREP|ADVANCED_BREP|BREP_WITH_VOIDS|SHELL_BASED_SURFACE_MODEL|CLOSED_SHELL|OPEN_SHELL|"
                  rb"POLY_LOOP|FACE_BOUND|FACE_OUTER_BOUND|EDGE_CURVE|TRIANGULATED_FACE_SET|TESSELLATED_|POLYLINE|B_SPLINE)")
PT = re.compile(rb"CARTESIAN_POINT\('[^']*',\(([^)]*)\)\)")


def s3():
    c = getattr(TL, "c", None)
    if c is None:
        with L:
            c = SESS.client("s3", region_name="ap-south-1", config=Config(max_pool_connections=64, retries={"max_attempts": 10, "mode": "standard"},
                                                                         connect_timeout=30, read_timeout=300))
        TL.c = c
    return c


def list_keys(prefix, delim=None):
    out = []; kw = dict(Bucket=B, Prefix=prefix)
    if delim: kw["Delimiter"] = delim
    for p in s3().get_paginator("list_objects_v2").paginate(**kw):
        out += p.get("CommonPrefixes", []) if delim else p.get("Contents", [])
    return out


_OLD = {}
def old_status(sk):
    m = re.search(r"/derived/db1-step/(Disk-\d)/by-sha256/([0-9a-f]{64})/", sk)
    if not m: return None, None
    key = f"{R}/derived/db1-step/{m.group(1)}/by-sha256/{m.group(2)}/result.json"
    if key not in _OLD:
        try: _OLD[key] = (json.loads(s3().get_object(Bucket=B, Key=key)["Body"].read()).get("status") or "").upper()
        except ClientError: _OLD[key] = "NO_RESULT"
    return m.group(2), _OLD[key]


def is_empty(key, size):
    if size > (256 << 10): return False
    body = s3().get_object(Bucket=B, Key=key)["Body"].read()
    if GEOM.search(body): return False
    pts = [p for p in PT.findall(body) if any(abs(float(v)) > 1e-9 for v in p.split(b",") if v.strip())]
    return not pts


def rows_of(pre):
    return [json.loads(l) for l in s3().get_object(Bucket=B, Key=pre + "manifest.jsonl")["Body"].read().decode().splitlines() if l.strip()]


def plan_one(pre):
    try: rows = rows_of(pre)
    except ClientError: return None
    steps = [r for r in rows if r["relpath"].startswith("model/step/")]
    rm = []
    for r in steps:
        sk = r.get("source_key") or ""
        if "/derived/db1-step/" not in sk: continue
        sha, st = old_status(sk)
        if st == "OK": continue
        if is_empty(pre + r["relpath"], int(r.get("bytes") or 0)):
            rm.append({"relpath": r["relpath"], "bytes": r.get("bytes"), "old_sha": sha, "old_status": st})
    if not rm: return None
    left = len(steps) - len(rm)
    return {"project": pre.split("/")[-2], "prefix": pre, "remove": rm, "steps_before": len(steps), "steps_after": left, "move_to_2d": left == 0}


def copy(src, dst):
    s3().copy_object(Bucket=B, Key=dst, CopySource={"Bucket": B, "Key": src}, MetadataDirective="COPY")


def apply_one(p):
    done = f"{OUT}/done/{p['project']}.json"
    try: s3().head_object(Bucket=B, Key=done); return "skip"
    except ClientError: pass
    pre = p["prefix"]; gone = {x["relpath"] for x in p["remove"]}
    rows = rows_of(pre)
    rows = [r for r in rows if r["relpath"] not in gone]
    steps = [r for r in rows if r["relpath"].startswith("model/step/")]
    pj = json.loads(s3().get_object(Bucket=B, Key=pre + "project.json")["Body"].read())
    pj.setdefault("slots", {})["model_step"] = len(steps)
    mf = pj.setdefault("model_formats", {})
    if steps: mf["step"] = len(steps)
    else: mf.pop("step", None)
    bs = collections.Counter(r.get("step_source") or "native" for r in steps); pj["model_step_by_source"] = dict(bs)
    conv = pj.get("conversions") or {}
    if "db1" in conv and isinstance(conv["db1"], dict):
        conv["db1"]["step_added"] = sum(1 for r in steps if (r.get("converted_from") or "").startswith("model/db1/"))
    pj["files"] = len(rows); pj["bytes"] = sum(int(r.get("bytes") or 0) for r in rows)
    pj["removed_empty_step"] = sorted(gone)
    w = pj.setdefault("warnings", [])
    msg = "header-only STEP files (no geometry) from the original DB1 pipeline's failed runs were removed"
    if msg not in w: w.append(msg)
    man_body = "\n".join(json.dumps(r) for r in rows).encode()
    if not steps:
        # back to main/2d: copy every remaining object, verify, then remove the 3d copy
        dst = f"{DEST}/2d/{p['project']}/"; pj["route"] = "2d"
        miss = pj.setdefault("missing", [])
        if "model_step" not in miss: miss.insert(0, "model_step")
        objs = [o for o in list_keys(pre) if o["Key"][len(pre):] not in gone and o["Key"][len(pre):] not in ("manifest.jsonl", "project.json")]
        with ThreadPoolExecutor(32) as ex: list(ex.map(lambda o: copy(o["Key"], dst + o["Key"][len(pre):]), objs))
        s3().put_object(Bucket=B, Key=dst + "manifest.jsonl", Body=man_body, ContentType="application/x-ndjson")
        s3().put_object(Bucket=B, Key=dst + "project.json", Body=json.dumps(pj, indent=1).encode(), ContentType="application/json")
        have = {o["Key"][len(dst):]: o["Size"] for o in list_keys(dst)}
        bad = [o for o in objs if have.get(o["Key"][len(pre):]) != o["Size"]]
        if bad: raise RuntimeError(f"{len(bad)} objects failed to copy to 2d; 3d copy kept")
        keys = [o["Key"] for o in list_keys(pre)]
        for i in range(0, len(keys), 1000):
            s3().delete_objects(Bucket=B, Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]]})
        res = "moved_to_2d"
    else:
        s3().put_object(Bucket=B, Key=pre + "manifest.jsonl", Body=man_body, ContentType="application/x-ndjson")
        keys = [pre + g for g in sorted(gone)]
        s3().delete_objects(Bucket=B, Delete={"Objects": [{"Key": k} for k in keys]})
        s3().put_object(Bucket=B, Key=pre + "project.json", Body=json.dumps(pj, indent=1).encode(), ContentType="application/json")
        res = "removed"
    s3().put_object(Bucket=B, Key=done, Body=json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "removed": sorted(gone), "result": res}).encode())
    return res


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if mode == "plan":
        pres = [p["Prefix"] for p in list_keys(f"{DEST}/3d/", "/")]
        with ThreadPoolExecutor(24) as ex: plan = [x for x in ex.map(plan_one, pres) if x]
        s3().put_object(Bucket=B, Key=f"{OUT}/plan.json", Body=json.dumps(plan).encode())
        print(json.dumps({"projects_checked": len(pres), "projects_with_empty_step": len(plan),
                          "rows_to_remove": sum(len(p["remove"]) for p in plan), "distinct_old_outputs": len({x["old_sha"] for p in plan for x in p["remove"]}),
                          "old_status": dict(collections.Counter(x["old_status"] for p in plan for x in p["remove"])),
                          "projects_left_without_step_move_to_2d": sum(1 for p in plan if p["move_to_2d"])}), flush=True)
        return
    plan = json.loads(s3().get_object(Bucket=B, Key=f"{OUT}/plan.json")["Body"].read())
    st = collections.Counter(); errs = []
    def safe(p):
        try: st[apply_one(p)] += 1
        except Exception as e: errs.append((p["project"], f"{type(e).__name__}: {str(e)[:200]}"))
    with ThreadPoolExecutor(8) as ex: list(ex.map(safe, plan))
    print("EMPTY-STEP DONE", dict(st), "errors", errs[:10], flush=True)
    if errs: sys.exit(3)


if __name__ == "__main__":
    main()
