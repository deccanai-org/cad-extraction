#!/usr/bin/env python3
"""POST-HOC COPY (2026-09-25): run from the operator workstation after the end-game, with PKG_STATE set to
a private prefix and PKG_NO_MOVES=1, to place conversions that finished after the boxes' plan was taken.
Add converted STEP (IFC->STEP and DB1->STEP) to the projpkg4 packages and re-route
projects that now hold STEP from main/2d to main/3d.

Mapping (no guessing):
  IFC  : a package's model/ifc file -> conversion job id = <etag>_<size> of its SOURCE
         object (manifest row etag/bytes) -> _state/ifc-step/results/<id>.json
  DB1  : a package's model/db1 file -> manifest source_key -> db1 sha256 (census row or
         the old pipeline's alias record) -> _state/db1-v2/results/<sha>.json
Only results with status 'ok' are placed.

Per project:
  model/step/<stem>.stp  (flat; 6-hex suffix on collision, derived from the conversion key)
  manifest.jsonl rows appended (modality 'step', role 'steel_model', converted_from, converter)
  project.json: slots.model_step, model_formats.step, missing, route, conversions
A 2d project that gains STEP is copied to main/3d/<project>/ (every object, server-side),
verified object-for-object, then its main/2d copy is removed.

  pkg_step.py plan            # writes the plan, changes nothing
  pkg_step.py apply [--threads N]
"""
import hashlib, json, os, sys, threading, time, collections
from concurrent.futures import ThreadPoolExecutor
import boto3, re
from botocore.config import Config
from botocore.exceptions import ClientError

B = "annotationprod"; R = "cad-disk-extract"; DEST = f"{R}/dataset/main"
SOURCES = os.environ.get("PKG_SOURCES", "all")          # ifc | db1 | all (separate passes keep separate state)
STATE = os.environ.get("PKG_STATE") or f"{R}/_control/packaging/step_v1_{SOURCES}"   # post-hoc passes use their own state
TH = int(os.environ.get("THREADS", "48"))
_tl = threading.local()


def _src(converted_from):
    return "db1" if converted_from.startswith("model/db1/") else ("ifc" if converted_from.startswith("model/ifc/") else "other")
# (PKG_SOURCES=ifc2 is the second IFC round; its rows are IFC-derived like round 1)


def _row_source(r):
    """native STEP from the archives / converted from IFC / converted from DB1 (this run, or the
    earlier Windows pipeline whose outputs live under derived/db1-step)"""
    if r.get("converted_from"): return _src(r["converted_from"])
    sk = r.get("source_key") or ""
    if "/derived/db1-step/" in sk: return "db1"
    if "/derived/ifc-step/" in sk or "/conversions/ifc-step/" in sk: return "ifc"
    if "/conversions/db1-step/" in sk: return "db1"
    return "native"


_SESS = None; _SLOCK = threading.Lock()


def s3():
    # ONE session per process (credentials resolved once): hundreds of threads each building a
    # session hit the instance-metadata rate limit -> NoCredentialsError
    global _SESS
    c = getattr(_tl, "c", None)
    if c is None:
        with _SLOCK:
            if _SESS is None:
                prof = os.environ.get("AWS_PROFILE_NAME")
                _SESS = boto3.Session(profile_name=prof) if prof else boto3.Session()
            # explicit timeouts: a single CopyObject of a multi-GB STEP once sat 3 h in a socket read
            c = _SESS.client("s3", region_name="ap-south-1", config=Config(
                max_pool_connections=TH + 16, retries={"max_attempts": 10, "mode": "standard"},
                connect_timeout=30, read_timeout=900, tcp_keepalive=True))
        _tl.c = c
    return c


def list_keys(prefix, delim=None):
    out = []; kw = dict(Bucket=B, Prefix=prefix)
    if delim: kw["Delimiter"] = delim
    for p in s3().get_paginator("list_objects_v2").paginate(**kw):
        out += p.get("CommonPrefixes", []) if delim else p.get("Contents", [])
    return out


def get_json(k):
    try: return json.loads(s3().get_object(Bucket=B, Key=k)["Body"].read())
    except ClientError: return None


def results(prefix):
    keys = [o["Key"] for o in list_keys(prefix)]
    with ThreadPoolExecutor(TH) as ex:
        return [r for r in ex.map(get_json, keys) if r]


def build_plan_ifc(round2=False):
    """IFC pass: packaged model/ifc objects -> conversion id <etag>_<size> (no manifest needed).
    round2: only conversions that were not in the round-1 plan (IFC files finished later), and
    never an IFC whose STEP row already exists in the project's manifest."""
    t0 = time.time()
    ifc = {r["id"]: r for r in results(f"{R}/_state/ifc-step/results/") if r.get("status") == "ok"}
    if round2:
        r1 = json.loads(s3().get_object(Bucket=B, Key=f"{R}/_control/packaging/step_v1_ifc/plan.json")["Body"].read())
        done_keys = {a["out_key"] for p in r1 for a in p["adds"]}
        ifc = {k: v for k, v in ifc.items() if v["out_key"] not in done_keys}
        print(f"round2: {len(ifc)} IFC conversions not in round 1", flush=True)
    print(f"ifc ok={len(ifc)} ({time.time()-t0:.0f}s)", flush=True)
    projects = [(route, p["Prefix"]) for route in ("3d", "2d") for p in list_keys(f"{DEST}/{route}/", "/")]
    print(f"projects {len(projects)}", flush=True)

    def plan_one(rp):
        route, pre = rp
        objs = list_keys(pre + "model/ifc/")
        if not objs: return None
        taken = {o["Key"].rsplit("/", 1)[1] for o in list_keys(pre + "model/step/")}
        adds = []; have_conv = None
        for o in sorted(objs, key=lambda o: o["Key"]):
            res = ifc.get(f"{o['ETag'].strip(chr(34)).replace('-', 'm')}_{o['Size']}")
            if not res: continue
            rel = o["Key"][len(pre):]
            if round2:
                if have_conv is None:
                    have_conv = {json.loads(l).get("converted_from") for l in s3().get_object(Bucket=B, Key=pre + "manifest.jsonl")["Body"].read().decode().splitlines() if l.strip()}
                if rel in have_conv: continue
            stem = rel.rsplit("/", 1)[1].rsplit(".", 1)[0]
            name = stem + ".step"
            if name in taken: name = f"{stem}-{hashlib.sha256(res['out_key'].encode()).hexdigest()[:6]}.step"
            taken.add(name)
            conv_label = res.get("converter") or "ifc2step5.py --mode hybrid --prec 2"
            fix = res.get("input_unzipped") or res.get("input_fix")
            if fix: conv_label += f" [input: {fix}]"
            adds.append(dict(name=name, out_key=res["out_key"], bytes=res.get("out_bytes"), converted_from=rel,
                             converter=conv_label))
        if not adds: return None
        return dict(project=pre.split("/")[-2], route=route, prefix=pre, adds=adds, move_to_3d=(route == "2d"))
    with ThreadPoolExecutor(TH) as ex:
        return [p for p in ex.map(plan_one, projects) if p]


FINAL = {"db1-2026-09-25g": None, "db1-2026-09-25f": {"ok"}}   # f ok outputs stay final under g


def _final_ok(r):
    """an older-code OK result is final only when code e would not have changed it"""
    a = (r.get("convert") or {}).get("axis_agreement")
    if a is None and isinstance(r.get("layout"), dict): a = r["layout"].get("axis_agreement")
    return a is None or a >= 0.9999


def build_plan_db1():
    """DB1 pass: a package's model/db1 file -> sha by (1) manifest source_key (census / old-pipeline aliases /
    job keys), (2) the SOURCE object's content identity (ETag+size of the job's key), and (3) the PACKAGED
    object's content identity: a copy whose source was uploaded differently (multipart vs single part ->
    different source ETag) is byte-identical to a mapped twin when its packaged ETag+size are equal.
    Only FINAL-code results with status ok are placed."""
    t0 = time.time()
    db1 = {}
    for r in results(f"{R}/_state/db1-v2/results/"):
        c = r.get("code")
        if r.get("status") == "ok" and c in FINAL: db1[r["sha"]] = r
    census = [json.loads(l) for l in s3().get_object(Bucket=B, Key=f"{R}/_control/db1-v2/census.jsonl")["Body"].read().decode().splitlines()]
    key2sha = {c["source_key"]: c["sha"] for c in census}
    for a in results(f"{R}/_state/db1-step/aliases/"):
        if a.get("source_key") and a.get("db1_sha256"): key2sha.setdefault(a["source_key"], a["db1_sha256"])
    jobs = json.loads(s3().get_object(Bucket=B, Key=f"{R}/_control/db1-v2/db1_jobs.json")["Body"].read())["jobs"]
    for j in jobs: key2sha.setdefault(j["key"], j["sha"])
    def ident(j):
        if j["sha"] not in db1: return None
        try:
            h = s3().head_object(Bucket=B, Key=j["key"]); return ((h["ETag"].strip('"'), h["ContentLength"]), j["sha"])
        except ClientError:
            return None
    with ThreadPoolExecutor(TH) as ex:
        ident2sha = dict(x for x in ex.map(ident, jobs) if x)
    print(f"db1 ok(final code)={len(db1)} keys mapped={len(key2sha)} identities={len(ident2sha)} ({time.time()-t0:.0f}s)", flush=True)
    projects = [(route, p["Prefix"]) for route in ("3d", "2d") for p in list_keys(f"{DEST}/{route}/", "/")]
    if os.environ.get("PKG_PROJECTS"):     # operator run: only the named projects (list of project ids, JSON)
        only = set(json.load(open(os.environ["PKG_PROJECTS"])))
        projects = [rp for rp in projects if rp[1].split("/")[-2] in only]
        print(f"restricted to {len(projects)} named projects", flush=True)

    def scan(rp):
        """pass 1: every model/db1 row of the project with its sha (source mapping) and packaged identity"""
        route, pre = rp
        objs = {o["Key"][len(pre):]: (o["ETag"].strip('"'), o["Size"]) for o in list_keys(pre + "model/db1/")}
        if not objs: return None
        rows = [json.loads(l) for l in s3().get_object(Bucket=B, Key=pre + "manifest.jsonl")["Body"].read().decode().splitlines() if l.strip()]
        have_conv = {r.get("converted_from") for r in rows if r.get("converted_from")}
        placed = {r.get("source_key") for r in rows if r["relpath"].startswith("model/step/")}
        taken = {o["Key"].rsplit("/", 1)[1] for o in list_keys(pre + "model/step/")}
        items = []
        for r in rows:
            if not r["relpath"].startswith("model/db1/"): continue
            sha = key2sha.get(r.get("source_key"))
            if not sha or sha not in db1:
                sha = ident2sha.get(((r.get("etag") or "").strip('"'), r.get("bytes"))) or sha
            items.append(dict(rel=r["relpath"], sha=sha if sha in db1 else None, pk=objs.get(r["relpath"]),
                              done=r["relpath"] in have_conv))
        return dict(route=route, pre=pre, items=items, placed=placed, taken=taken)
    with ThreadPoolExecutor(TH) as ex:
        scans = [x for x in ex.map(scan, projects) if x]
    pk2sha = {}; clash = set()
    for sc in scans:
        for it in sc["items"]:
            if it["sha"] and it["pk"]:
                if pk2sha.get(it["pk"], it["sha"]) != it["sha"]: clash.add(it["pk"])
                pk2sha[it["pk"]] = it["sha"]
    for k in clash: pk2sha.pop(k, None)    # never guess: an identity seen with two different shas is not used
    n_pk = 0; plan = []
    for sc in scans:
        adds = []; placed_here = set(sc["placed"]); taken = set(sc["taken"])
        for it in sc["items"]:
            if it["done"]: continue
            sha = it["sha"]
            if not sha and it["pk"] in pk2sha: sha = pk2sha[it["pk"]]; n_pk += 1
            res = db1.get(sha) if sha else None
            if not res: continue
            if res["out_key"] in placed_here: continue      # identical DB1 twice in one project: one STEP
            placed_here.add(res["out_key"])
            stem = it["rel"].rsplit("/", 1)[1].rsplit(".", 1)[0]
            name = stem + ".step"
            if name in taken: name = f"{stem}-{hashlib.sha256(res['out_key'].encode()).hexdigest()[:6]}.step"
            taken.add(name)
            adds.append(dict(name=name, out_key=res["out_key"], bytes=res.get("out_bytes"), converted_from=it["rel"],
                             converter="db1dec+db1step (" + res.get("code", "") + ") -> ifc2step5.py --mode hybrid --prec 2"))
        if adds:
            plan.append(dict(project=sc["pre"].split("/")[-2], route=sc["route"], prefix=sc["pre"], adds=adds, move_to_3d=(sc["route"] == "2d")))
    print(f"packaged-identity matches used: {n_pk}  identity clashes dropped: {len(clash)}", flush=True)
    return plan


def build_plan():
    if SOURCES == "ifc": return build_plan_ifc()
    if SOURCES == "ifc2": return build_plan_ifc(round2=True)
    if SOURCES == "db1": return build_plan_db1()
    t0 = time.time()
    ifc = {r["id"]: r for r in results(f"{R}/_state/ifc-step/results/") if r.get("status") == "ok"}
    db1 = {r["sha"]: r for r in results(f"{R}/_state/db1-v2/results/") if r.get("status") == "ok"}
    # source_key -> sha for every DB1 copy
    census = [json.loads(l) for l in s3().get_object(Bucket=B, Key=f"{R}/_control/db1-v2/census.jsonl")["Body"].read().decode().splitlines()]
    key2sha = {c["source_key"]: c["sha"] for c in census}
    for a in results(f"{R}/_state/db1-step/aliases/"):
        if a.get("source_key") and a.get("db1_sha256"): key2sha.setdefault(a["source_key"], a["db1_sha256"])
    print(f"ifc ok={len(ifc)} db1 ok={len(db1)} db1 keys mapped={len(key2sha)} ({time.time()-t0:.0f}s)", flush=True)
    projects = [(route, p["Prefix"]) for route in ("3d", "2d") for p in list_keys(f"{DEST}/{route}/", "/")]
    print(f"projects {len(projects)}", flush=True)

    def plan_one(rp):
        route, pre = rp
        man = s3().get_object(Bucket=B, Key=pre + "manifest.jsonl")["Body"].read().decode().splitlines()
        rows = [json.loads(l) for l in man if l.strip()]
        taken = {r["relpath"].split("/", 2)[2] for r in rows if r["relpath"].startswith("model/step/")}
        # IFC jobs were keyed by the PACKAGED object's etag+size (copies of multipart
        # sources get a new etag), so read those rather than the manifest's source etag
        ifc_objs = {o["Key"][len(pre):]: (o["ETag"].strip('"'), o["Size"]) for o in list_keys(pre + "model/ifc/")}
        adds = []
        for r in rows:
            src = None
            if r["relpath"].startswith("model/ifc/"):
                et, sz = ifc_objs.get(r["relpath"], (r.get("etag") or "", r["bytes"]))
                res = ifc.get(f"{et.replace('-', 'm')}_{sz}")
                if res: src = (res["out_key"], res.get("out_bytes"), "ifc2step5.py --mode hybrid --prec 2")
            elif r["relpath"].startswith("model/db1/"):
                sha = key2sha.get(r.get("source_key"))
                res = db1.get(sha) if sha else None
                if res: src = (res["out_key"], res.get("out_bytes"), "db1dec+db1step -> ifc2step5.py --mode hybrid --prec 2")
            if not src: continue
            stem = r["relpath"].rsplit("/", 1)[1].rsplit(".", 1)[0]
            name = stem + ".step"
            if name in taken:
                name = f"{stem}-{hashlib.sha256(src[0].encode()).hexdigest()[:6]}.step"
            taken.add(name)
            adds.append(dict(name=name, out_key=src[0], bytes=src[1], converted_from=r["relpath"], converter=src[2]))
        if not adds: return None
        return dict(project=pre.split("/")[-2], route=route, prefix=pre, adds=adds,
                    move_to_3d=(route == "2d"))
    with ThreadPoolExecutor(TH) as ex:
        plan = [p for p in ex.map(plan_one, projects) if p]
    return plan


def copy(src, dst, size=None):
    c = s3()
    if size is None: size = c.head_object(Bucket=B, Key=src)["ContentLength"]
    if size <= 1024 ** 3:   # multipart above 1 GB keeps every request short
        c.copy_object(Bucket=B, Key=dst, CopySource={"Bucket": B, "Key": src}, MetadataDirective="COPY"); return
    h = c.head_object(Bucket=B, Key=src)     # keep the source's content type / metadata, as CopyObject does
    kw = {"Metadata": h.get("Metadata") or {}}
    if h.get("ContentType"): kw["ContentType"] = h["ContentType"]
    mpu = c.create_multipart_upload(Bucket=B, Key=dst, **kw); uid = mpu["UploadId"]
    P = 512 * 1024 ** 2
    ranges = [(i + 1, pos, min(pos + P, size) - 1) for i, pos in enumerate(range(0, size, P))]
    def part(rg):
        n, a0, a1 = rg
        r = s3().upload_part_copy(Bucket=B, Key=dst, UploadId=uid, PartNumber=n, CopySource={"Bucket": B, "Key": src},
                                  CopySourceRange=f"bytes={a0}-{a1}")
        return {"ETag": r["CopyPartResult"]["ETag"], "PartNumber": n}
    try:
        # parts copy concurrently (a 40 GB STEP is 80 parts; sequential copies took ~15 min)
        with ThreadPoolExecutor(16) as ex:
            parts = sorted(ex.map(part, ranges), key=lambda x: x["PartNumber"])
        c.complete_multipart_upload(Bucket=B, Key=dst, UploadId=uid, MultipartUpload={"Parts": parts})
    except Exception:
        c.abort_multipart_upload(Bucket=B, Key=dst, UploadId=uid); raise


def apply_one(p):
    done_key = f"{STATE}/done/{p['project']}.json"
    if get_json(done_key): return "skip"
    src_pre = p["prefix"]; dst_pre = f"{DEST}/3d/{p['project']}/"
    # 1. move a 2d project to 3d (copy everything, verify, remove the 2d copy last)
    if p["move_to_3d"]:
        objs = list_keys(src_pre)
        with ThreadPoolExecutor(TH) as ex:
            list(ex.map(lambda o: copy(o["Key"], dst_pre + o["Key"][len(src_pre):], o["Size"]), objs))
        have = {o["Key"][len(dst_pre):]: o["Size"] for o in list_keys(dst_pre)}
        miss = [o for o in objs if have.get(o["Key"][len(src_pre):]) != o["Size"]]
        if miss: raise RuntimeError(f"{p['project']}: {len(miss)} objects failed to copy; 2d copy kept")
    # 2. place the STEP files (concurrently)
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda a: copy(a["out_key"], dst_pre + "model/step/" + a["name"], a.get("bytes")), p["adds"]))
    # 3. manifest + project.json
    rows = [json.loads(l) for l in s3().get_object(Bucket=B, Key=dst_pre + "manifest.jsonl")["Body"].read().decode().splitlines() if l.strip()]
    have_rel = {r["relpath"] for r in rows}
    for a in p["adds"]:
        rel = "model/step/" + a["name"]
        if rel in have_rel: continue
        h = s3().head_object(Bucket=B, Key=dst_pre + rel)
        rows.append({"project_id": p["project"], "relpath": rel, "modality": "step", "role": "steel_model",
                     "bytes": h["ContentLength"], "sha256": None, "parser_ok": True, "units": "mm", "supersedes": None,
                     "etag": h["ETag"].strip('"'), "source_key": a["out_key"],
                     "converted_from": a["converted_from"], "converter": a["converter"],
                     "step_source": _src(a["converted_from"])})
    for r in rows:   # every STEP row says where it came from (native file / IFC / DB1 conversion)
        if r["relpath"].startswith("model/step/") and "step_source" not in r:
            r["step_source"] = _row_source(r)
    s3().put_object(Bucket=B, Key=dst_pre + "manifest.jsonl", Body="\n".join(json.dumps(r) for r in rows).encode(), ContentType="application/x-ndjson")
    pj = get_json(dst_pre + "project.json") or {}
    nstep = sum(1 for r in rows if r["relpath"].startswith("model/step/"))
    pj.setdefault("slots", {})["model_step"] = nstep
    mf = pj.setdefault("model_formats", {}); mf["step"] = nstep
    pj["missing"] = [m for m in pj.get("missing", []) if m != "model_step"]
    pj["route"] = "3d"
    # per-source conversion summary, MERGED across passes (IFC pass, DB1 pass)
    conv = pj.get("conversions") or {}
    if "by_converter" in conv:   # first-pass (IFC) flat format -> keyed by source
        conv = {"ifc": {"step_added": conv.get("step_added"), "converter": "ifc2step5.py --mode hybrid --prec 2",
                        "added_at": conv.get("added_at")}}
    srcs = collections.Counter(_src(a["converted_from"]) for a in p["adds"])
    for k, n in srcs.items():
        # post-hoc pass: the count is taken from the manifest (every STEP row converted from this source type)
        conv[k] = {"step_added": sum(1 for r in rows if r["relpath"].startswith("model/step/") and _src(r.get("converted_from") or "") == k),
                   "converter": next(a["converter"] for a in p["adds"] if _src(a["converted_from"]) == k),
                   "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    pj["conversions"] = conv
    by = collections.Counter(r.get("step_source") or _row_source(r) for r in rows if r["relpath"].startswith("model/step/"))
    pj["model_step_by_source"] = dict(by)
    pj["files"] = len(rows); pj["bytes"] = sum(int(r.get("bytes") or 0) for r in rows)
    s3().put_object(Bucket=B, Key=dst_pre + "project.json", Body=json.dumps(pj, indent=1).encode(), ContentType="application/json")
    # 4. remove the 2d copy only after the 3d copy is complete and verified
    if p["move_to_3d"]:
        keys = [o["Key"] for o in list_keys(src_pre)]
        for i in range(0, len(keys), 1000):
            s3().delete_objects(Bucket=B, Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]]})
    s3().put_object(Bucket=B, Key=done_key, Body=json.dumps({"at": time.time(), "adds": len(p["adds"]), "moved": p["move_to_3d"]}).encode())
    return "moved" if p["move_to_3d"] else "added"


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if mode == "plan":
        plan = build_plan()
        if os.environ.get("PKG_NO_MOVES") == "1":
            held = [p for p in plan if p["move_to_3d"]]
            for p in held: print("HELD (needs 2d->3d move):", p["project"], len(p["adds"]), "STEP", flush=True)
            plan = [p for p in plan if not p["move_to_3d"]]
        s3().put_object(Bucket=B, Key=f"{STATE}/plan.json", Body=json.dumps(plan).encode())
        mv = [p for p in plan if p["move_to_3d"]]
        print(f"projects gaining STEP: {len(plan)}  (already 3d: {len(plan)-len(mv)}, 2d->3d moves: {len(mv)})")
        print(f"STEP files to place: {sum(len(p['adds']) for p in plan)}  by converter: "
              f"{dict(collections.Counter(a['converter'].split(' ')[0] for p in plan for a in p['adds']))}")
        return
    if mode == "retag":
        ifc_done = {o["Key"].rsplit("/", 1)[1][:-5] for o in list_keys(f"{R}/_control/packaging/step_v1_ifc/done/")}
        db1_done = {o["Key"].rsplit("/", 1)[1][:-5] for o in list_keys(f"{R}/_control/packaging/step_v1_db1/done/")}
        def retag(proj):
            pre = f"{DEST}/3d/{proj}/"
            rows = [json.loads(l) for l in s3().get_object(Bucket=B, Key=pre + "manifest.jsonl")["Body"].read().decode().splitlines() if l.strip()]
            changed = False
            for r in rows:
                if r["relpath"].startswith("model/step/") and "step_source" not in r:
                    r["step_source"] = _row_source(r); changed = True
            if changed:
                s3().put_object(Bucket=B, Key=pre + "manifest.jsonl", Body="\n".join(json.dumps(r) for r in rows).encode(), ContentType="application/x-ndjson")
            pj = get_json(pre + "project.json") or {}
            conv = pj.get("conversions") or {}
            if "by_converter" in conv:
                pj["conversions"] = {"ifc": {"step_added": conv.get("step_added"), "converter": "ifc2step5.py --mode hybrid --prec 2", "added_at": conv.get("added_at")}}
            pj["model_step_by_source"] = dict(collections.Counter(r["step_source"] for r in rows if r["relpath"].startswith("model/step/")))
            s3().put_object(Bucket=B, Key=pre + "project.json", Body=json.dumps(pj, indent=1).encode(), ContentType="application/json")
            return 1
        # every 3d project: STEP rows get step_source (native / ifc / db1), project.json gets
        # model_step_by_source; projects rewritten by the DB1 pass are already tagged
        todo = sorted(p["Prefix"].split("/")[-2] for p in list_keys(f"{DEST}/3d/", "/"))
        todo = [t for t in todo if t not in db1_done]
        sh = os.environ.get("PKG_SHARD")
        if sh:
            import zlib
            i, n = (int(x) for x in sh.split("/")); todo = [t for t in todo if zlib.crc32(t.encode()) % n == i]
        def safe(t):
            try: return retag(t)
            except Exception as e: print(f"ERROR {t}: {type(e).__name__}: {str(e)[:200]}", flush=True); return 0
        with ThreadPoolExecutor(16) as ex: n = sum(ex.map(safe, todo))
        print("RETAG DONE", n, "of", len(todo), flush=True); return
    plan = json.loads(s3().get_object(Bucket=B, Key=f"{STATE}/plan.json")["Body"].read())
    st = collections.Counter()
    # PKG_SHARD="i/N": this process owns the projects with crc32(project) % N == i (processes on
    # any number of boxes never touch the same project; apply_one is idempotent on restart)
    sh = os.environ.get("PKG_SHARD")
    if sh:
        import zlib
        i, n = (int(x) for x in sh.split("/"))
        plan = [p for p in plan if zlib.crc32(p["project"].encode()) % n == i]
        sub = os.environ.get("PKG_SUBSHARD")          # split a heavy shard across more processes
        if sub:
            j, m = (int(x) for x in sub.split("/"))
            plan = [p for p in plan if zlib.crc32((p["project"] + "#sub").encode()) % m == j]
    print(time.strftime("%H:%M:%S"), f"shard {sh or 'all'}: {len(plan)} projects", flush=True)
    def safe(p):
        t = time.time()
        try: r = apply_one(p)
        except Exception as e:
            print(f"ERROR {p['project']}: {type(e).__name__}: {str(e)[:300]}", flush=True); return "error"
        print(time.strftime("%H:%M:%S"), r, p["project"][:80], f"{time.time()-t:.0f}s", flush=True)
        return r
    from concurrent.futures import as_completed
    with ThreadPoolExecutor(int(os.environ.get("PROJ_THREADS", "8"))) as ex:
        for f in as_completed([ex.submit(safe, p) for p in plan]):
            st[f.result()] += 1
    print("APPLY DONE", dict(st), flush=True)
    if st.get("error"): sys.exit(3)


if __name__ == "__main__":
    main()
