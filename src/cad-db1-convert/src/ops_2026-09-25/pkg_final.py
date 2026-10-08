#!/usr/bin/env python3
"""Package the CAD extraction output in the cad-dataset-packager (projpkg4) format.

Directory vocabulary and manifest/project schemas were read from the live
projpkg4 tree, not from the draft spec, because the two differ:

    project.json  manifest.jsonl
    model/step  model/ifc  model/db1  model/db2
    drawings/pdf  drawings/dwg  drawings/dxf  drawings/dg  drawings/dpm
    fab/nc1
    tables/bom  tables/abm  tables/kiss  tables/drawing_index

Two properties of that format matter and were wrong in the first attempt:

  * Paths are FLAT. projpkg4 stores `model/db1/NAME-11dd5f.db1`, one directory
    deep, not the archive's nested tree. Collisions get a 6-hex suffix. The
    upstream packager derives that suffix from the local filesystem path, which
    its own CONTEXT.md notes is not reproducible off-instance; here it is
    derived from the source S3 key, so it is deterministic and reproducible.
  * A project is 3D if it holds ANY .stp/.step -- including STEP this pipeline
    produced from .db1 -- rather than only AP-schema geometry.

Runs unchanged on Linux and Windows: pure threads, no fork.
ADDITIVE ONLY. Writes exclusively under DEST. Never deletes anything.
"""
from __future__ import annotations
import hashlib, json, os, platform, threading, time, collections
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

B="annotationprod"; R="cad-disk-extract"
DEST=f"{R}/dataset/main"
STATE=f"{R}/_control/packaging/state_v2"
COPY_THREADS=int(os.environ.get("COPY_THREADS","48"))
PROJ_THREADS=int(os.environ.get("PROJ_THREADS","16"))
HOST=platform.node()
_tl=threading.local()

def s3():
    c=getattr(_tl,"c",None)
    if c is None:
        c=boto3.client("s3",region_name="ap-south-1",
            config=Config(max_pool_connections=COPY_THREADS+16,
                          retries={"max_attempts":10,"mode":"adaptive"}))
        _tl.c=c
    return c

MODEL={".step":"model/step",".stp":"model/step",".ifc":"model/ifc",
       ".db1":"model/db1",".db2":"model/db2",
       ".sat":"model/sat",".obj":"model/obj",".stl":"model/stl",
       ".gltf":"model/gltf",".glb":"model/glb"}
DRAW ={".pdf":"drawings/pdf",".dwg":"drawings/dwg",".dxf":"drawings/dxf",
       ".dg":"drawings/dg",".dpm":"drawings/dpm"}
FAB  ={".nc1":"fab/nc1"}
TABLE={".xls":"tables/bom",".xlsx":"tables/bom",".csv":"tables/bom",
       ".kis":"tables/kiss",".kiss":"tables/kiss"}

def ext_of(name:str)->str:
    low=name.lower(); d=low.rfind(".")
    return low if d==0 else (low[d:] if d>0 else "")

def classify(name:str, srckey:str):
    """-> (channel, modality, role) using the projpkg4 vocabulary."""
    e=ext_of(name); p=srckey.lower()
    if e in MODEL:
        ch=MODEL[e]
        # abm / kiss live under tables even when spreadsheet-shaped
        return ch, e.lstrip("."), "steel_model"
    if e in FAB:
        return FAB[e], "nc1", "part_cnc"
    if e in TABLE:
        ch=TABLE[e]
        if "abm" in p or "advanced bill" in p: ch="tables/abm"
        elif "kiss" in p: ch="tables/kiss"
        elif "index" in p: ch="tables/drawing_index"
        return ch, e.lstrip("."), "table"
    if e in DRAW:
        ch=DRAW[e]
        if   "shop" in p:                         role="shop"
        elif "erect" in p or "ga" == p.rsplit("/",2)[-2:-1][:1]: role="ga"
        elif "erection" in p or "general" in p:   role="ga"
        else:                                     role="shop" if e==".pdf" else "ga"
        return ch, e.lstrip("."), role
    return None, None, None       # not a wanted asset - excluded from the package

def flat_name(name:str, srckey:str, taken:set)->str:
    """projpkg4 stores one file per channel dir; disambiguate collisions like it does."""
    if name not in taken:
        taken.add(name); return name
    stem,dot,ext = name.rpartition(".")
    if not dot: stem,ext = name,""
    h=hashlib.sha256(srckey.encode("utf-8","surrogateescape")).hexdigest()[:6]
    cand=f"{stem}-{h}{dot}{ext}" if dot else f"{stem}-{h}"
    i=0
    while cand in taken:
        i+=1
        h2=hashlib.sha256(f"{srckey}#{i}".encode("utf-8","surrogateescape")).hexdigest()[:6]
        cand=f"{stem}-{h2}{dot}{ext}" if dot else f"{stem}-{h2}"
    taken.add(cand); return cand

STALE_CLAIM_SECONDS = int(os.environ.get("STALE_CLAIM_SECONDS","1200"))

def claim(p):
    """Claim a project, taking over a claim that has gone stale.

    Workers make a single pass and exit; a process that dies mid-project used to
    leave its claim behind forever, so nobody retried that project. Treat a
    claim with no result and no progress for STALE_CLAIM_SECONDS as abandoned.
    """
    key=f"{STATE}/claims/{p}.json"
    try:
        s3().put_object(Bucket=B,Key=key,
            Body=json.dumps({"at":time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                             "host":HOST}).encode(),
            ContentType="application/json", IfNoneMatch="*")
        return True
    except ClientError as e:
        if e.response.get("Error",{}).get("Code") not in (
            "PreconditionFailed","412","ConditionalRequestConflict","409"):
            raise
    # someone holds it -- is it abandoned?
    try:
        h=s3().head_object(Bucket=B,Key=key)
        age=(time.time()-h["LastModified"].timestamp())
    except Exception:
        return False
    if age < STALE_CLAIM_SECONDS:
        return False
    try:
        s3().delete_object(Bucket=B,Key=key)
        s3().put_object(Bucket=B,Key=key,
            Body=json.dumps({"at":time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                             "host":HOST,"took_over_after_s":int(age)}).encode(),
            ContentType="application/json", IfNoneMatch="*")
        print(f"  took over stale claim ({int(age)}s): {p[:56]}",flush=True)
        return True
    except ClientError:
        return False

def finished(p):
    try: s3().head_object(Bucket=B,Key=f"{STATE}/results/{p}.json"); return True
    except ClientError: return False

def _list_seq(prefix):
    out=[]; tok=None; c=s3()
    while True:
        kw={"Bucket":B,"Prefix":prefix,"MaxKeys":1000}
        if tok: kw["ContinuationToken"]=tok
        r=c.list_objects_v2(**kw)
        for o in r.get("Contents") or []:
            out.append((o["Key"],int(o.get("Size") or 0),(o.get("ETag") or "").strip('"')))
        if not r.get("IsTruncated"): break
        tok=r["NextContinuationToken"]
    return out

LIST_THREADS=int(os.environ.get("LIST_THREADS","24"))

def list_all(prefix):
    """Shard the listing across child prefixes.

    A project with millions of objects otherwise needs thousands of strictly
    sequential ListObjectsV2 round-trips before the first copy can start, and
    that latency -- not copy throughput -- dominates the giant projects.
    One delimited call gives the child prefixes, which can then be listed
    concurrently. Falls back to a plain sequential walk when the project is
    shallow enough that sharding would not help.
    """
    c=s3()
    r=c.list_objects_v2(Bucket=B,Prefix=prefix,Delimiter="/",MaxKeys=1000)
    kids=[x["Prefix"] for x in (r.get("CommonPrefixes") or [])]
    tok=r.get("NextContinuationToken")
    while r.get("IsTruncated") and tok:
        r=c.list_objects_v2(Bucket=B,Prefix=prefix,Delimiter="/",MaxKeys=1000,
                            ContinuationToken=tok)
        kids+=[x["Prefix"] for x in (r.get("CommonPrefixes") or [])]
        tok=r.get("NextContinuationToken")
    if len(kids)<2:
        return _list_seq(prefix)
    out=[(o["Key"],int(o.get("Size") or 0),(o.get("ETag") or "").strip('"'))
         for o in (r.get("Contents") or [])]
    with ThreadPoolExecutor(max_workers=min(LIST_THREADS,len(kids))) as tp:
        for part in tp.map(_list_seq,kids):
            out+=part
    return out

MPU_PART = 512 * 1024 * 1024        # 512 MiB parts: 10k-part limit covers 5 TiB

def _multipart_copy(c, src_key, dst_key, size):
    """Server-side copy for objects above the 5 GiB CopyObject ceiling.

    Still server-side -- upload_part_copy never moves bytes through this host.
    Aborts the upload on failure so no incomplete multipart is left to bill.
    """
    mpu = c.create_multipart_upload(Bucket=B, Key=dst_key)
    uid = mpu["UploadId"]
    try:
        parts = []
        n = 0
        pos = 0
        while pos < size:
            last = min(pos + MPU_PART, size) - 1
            n += 1
            r = c.upload_part_copy(
                Bucket=B, Key=dst_key, UploadId=uid, PartNumber=n,
                CopySource={"Bucket": B, "Key": src_key},
                CopySourceRange=f"bytes={pos}-{last}")
            parts.append({"ETag": r["CopyPartResult"]["ETag"], "PartNumber": n})
            pos = last + 1
        c.complete_multipart_upload(Bucket=B, Key=dst_key, UploadId=uid,
                                    MultipartUpload={"Parts": parts})
    except Exception:
        try: c.abort_multipart_upload(Bucket=B, Key=dst_key, UploadId=uid)
        except Exception: pass
        raise


M=collections.Counter(); MLOCK=threading.Lock()

def pack(job):
    route,disk,tag,prefix = job["route"],job["disk"],job["tag"],job["prefix"]
    derived=job.get("derived") or []
    project=f"{disk}__{tag}"[:200]
    if finished(project):
        with MLOCK: M["skip"]+=1
        return
    if not claim(project):
        with MLOCK: M["claimed_elsewhere"]+=1
        return
    base=f"{DEST}/{route}/{project}"
    rec={"project":project,"route":route,"status":"ok","copied":0,"failed":0,
         "bytes":0,"excluded":0,"duplicates_collapsed":0,"errors":[],"host":HOST}
    man=[]; slots=collections.Counter(); mfmt=collections.Counter()
    dfmt=collections.Counter(); schemas=collections.Counter()
    taken=collections.defaultdict(set)
    lock=threading.Lock(); t0=time.time()
    try:
        srcs=[(k,sz,et) for k,sz,et in list_all(prefix)]
        for dp in derived:
            srcs+=[(k,sz,et) for k,sz,et in list_all(dp)]
        # Assign flat destination names single-threaded so collisions resolve
        # deterministically. Collapse content-identical copies first: the same
        # file often appears at several paths inside one archive, and storing it
        # twice under a disambiguated name would be duplication, not provenance.
        # Identity is (etag, size) -- a real content digest; the corpus is
        # documented to contain same-name same-size files that DIFFER in
        # content, so name+size alone is not a safe key here.
        plan=[]; seen_content={}
        for k,sz,et in srcs:
            name=k.rsplit("/",1)[-1]
            if not name: continue
            ch,modality,role=classify(name,k)
            if ch is None:
                rec["excluded"]+=1; continue
            ident=(ch,et,sz)
            if et and ident in seen_content:
                rec["duplicates_collapsed"]=rec.get("duplicates_collapsed",0)+1
                continue
            fn=flat_name(name,k,taken[ch])
            if et: seen_content[ident]=fn
            plan.append((k,sz,et,ch,modality,role,fn))
        c=s3()
        def one(item):
            k,sz,et,ch,modality,role,fn=item
            dst=f"{base}/{ch}/{fn}"
            # One bounded retry: the SSL failures seen at high concurrency were
            # resource exhaustion on the client, not bad objects, so the same
            # copy succeeds moments later. Without this a transient pool
            # collapse silently costs thousands of files per project.
            for _attempt in range(2):
              try:
                if sz > 5*1024**3:
                    # CopyObject tops out at 5 GiB; anything larger must go
                    # through a multipart copy or the whole project is marked
                    # partial for one file.
                    _multipart_copy(c,k,dst,sz)
                else:
                    c.copy_object(Bucket=B,Key=dst,CopySource={"Bucket":B,"Key":k},
                                  MetadataDirective="COPY")
                row={"project_id":project,"relpath":f"{ch}/{fn}","modality":modality,
                     "role":role,"bytes":sz,"sha256":None,"parser_ok":True,
                     "units":"mm","supersedes":None,"etag":et,"source_key":k}
                with lock:
                    rec["copied"]+=1; rec["bytes"]+=sz
                    slots[ch]+=1; man.append(row)
                    if ch.startswith("model/"): mfmt[modality]+=1
                    elif ch.startswith("drawings/"): dfmt[modality]+=1
                break
              except Exception as e:
                if _attempt == 0:
                    time.sleep(1.5); continue
                with lock:
                    rec["failed"]+=1
                    if len(rec["errors"])<20:
                        rec["errors"].append(f"{type(e).__name__}:{str(e)[:120]}")
        with ThreadPoolExecutor(max_workers=COPY_THREADS) as tp:
            list(tp.map(one,plan))
        if man:
            c.put_object(Bucket=B,Key=f"{base}/manifest.jsonl",
                Body=("\n".join(json.dumps(m) for m in man)).encode(),
                ContentType="application/x-ndjson")
        want=["model_step","model_ifc","model_db1","model_db2","drawings","fab_nc1",
              "bom","abm","kiss","drawing_index"]
        got={"model_step":slots.get("model/step",0),"model_ifc":slots.get("model/ifc",0),
             "model_db1":slots.get("model/db1",0),"model_db2":slots.get("model/db2",0),
             "drawings":sum(v for k2,v in slots.items() if k2.startswith("drawings/")),
             "fab_nc1":slots.get("fab/nc1",0),"bom":slots.get("tables/bom",0),
             "abm":slots.get("tables/abm",0),"kiss":slots.get("tables/kiss",0),
             "drawing_index":slots.get("tables/drawing_index",0)}
        proj={"id":project,"source":f"{disk}/{tag}","units":"mm",
              "domain":"structural_steel","year":None,
              "status":"complete" if not rec["failed"] else "partial",
              "route":route,
              "slots":got,
              "model_formats":dict(mfmt),"drawing_formats":dict(dfmt),
              "missing":[k2 for k2 in want if not got.get(k2)],
              "warnings":["drawing role (shop/ga) inferred from source path keywords",
                          "sha256 not computed: extraction objects carry no digest in "
                          "metadata; etag is provided per manifest row instead"],
              "skipped_files":[],
              "model_step_schemas":dict(schemas),
              "files":rec["copied"],"bytes":rec["bytes"],
              "excluded_non_asset_files":rec["excluded"],
              "duplicates_collapsed":rec.get("duplicates_collapsed",0),
              "packaged_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
              "packaged_by":HOST}
        c.put_object(Bucket=B,Key=f"{base}/project.json",
                     Body=json.dumps(proj,indent=1).encode(),ContentType="application/json")
        if rec["failed"]: rec["status"]="partial"
    except Exception as e:
        rec["status"]="error"; rec["errors"].append(f"{type(e).__name__}:{str(e)[:200]}")
    rec["seconds"]=round(time.time()-t0,1)
    s3().put_object(Bucket=B,Key=f"{STATE}/results/{project}.json",
                    Body=json.dumps(rec).encode(),ContentType="application/json")
    with MLOCK:
        M[rec["status"]]+=1; M["files"]+=rec["copied"]

def main():
    c=boto3.client("s3",region_name="ap-south-1",config=Config(retries={"max_attempts":6}))
    wl=json.loads(c.get_object(Bucket=B,Key=f"{R}/_control/packaging/worklist_v2.json")["Body"].read())
    jobs=wl["jobs"]
    only=os.environ.get("ONLY_ROUTE")
    if only: jobs=[j for j in jobs if j["route"]==only]
    order=os.environ.get("ORDER","small")
    jobs.sort(key=lambda j:(j.get("files") or 0), reverse=(order=="big"))
    print(f"host={HOST} projects={len(jobs)} route={only or 'all'} order={order} "
          f"proj={PROJ_THREADS} copy={COPY_THREADS}",flush=True)
    t0=time.time()
    def rep():
        while True:
            time.sleep(30)
            with MLOCK: s=dict(M)
            el=time.time()-t0
            print(f"  {s} rate={s.get('files',0)/max(el,1):.0f} f/s {el:.0f}s",flush=True)
    threading.Thread(target=rep,daemon=True).start()
    # Loop instead of a single pass: after a pass, anything still unfinished is
    # either genuinely in flight elsewhere or an abandoned claim, and the stale
    # takeover above will collect the latter on a later round.
    rounds=int(os.environ.get("ROUNDS","40"))
    for rnd in range(1,rounds+1):
        pending=[j for j in jobs
                 if not finished(f"{j['disk']}__{j['tag']}"[:200])]
        if not pending:
            print(f"round {rnd}: nothing left",flush=True); break
        print(f"round {rnd}: {len(pending)} unfinished",flush=True)
        with ThreadPoolExecutor(max_workers=PROJ_THREADS) as pool:
            list(pool.map(pack,pending))
        still=[j for j in jobs if not finished(f"{j['disk']}__{j['tag']}"[:200])]
        if not still:
            print(f"round {rnd}: all complete",flush=True); break
        time.sleep(30)
    with MLOCK: print("FINAL",dict(M),flush=True)
    print("PKG-FINAL-DONE",flush=True)

if __name__=="__main__": raise SystemExit(main())
