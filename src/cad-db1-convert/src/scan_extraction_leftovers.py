"""Scan every EC2 extraction result for what could NOT be read: password-protected nested archives
(encrypted_nested_archives / encrypted_blocked with the member names 7-Zip reported), archives whose
7-Zip run ended in a fatal-but-accepted rc=2, failure classifications/diagnostics, non-ok statuses.
Writes cad-disk-extract/_control/packaging/report/extraction_leftovers.json"""
import json, boto3, threading, time
from concurrent.futures import ThreadPoolExecutor
B = "annotationprod"; P = "cad-disk-extract/_state/ec2-results/"; OUT = "cad-disk-extract/_control/packaging/report/extraction_leftovers.json"
tl = threading.local(); SESS = boto3.Session(); LOCK = threading.Lock()
def s3():
    c = getattr(tl, "c", None)
    if c is None:
        with LOCK: c = SESS.client("s3", region_name="ap-south-1")
        tl.c = c
    return c
keys = [o["Key"] for pg in s3().get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=P) for o in pg.get("Contents", []) if o["Key"].endswith(".json")]
print(len(keys), "results", flush=True)
def one(k):
    for i in range(4):
        try:
            d = json.loads(s3().get_object(Bucket=B, Key=k)["Body"].read())
            break
        except Exception as e:
            err = e; time.sleep(2)
    else:
        return {"result_key": k, "read_error": str(err)[:200]}
    row = {"source_key": d.get("source_key"), "disk": d.get("disk"), "status": d.get("status"), "archive_bytes": d.get("archive_bytes"),
           "stored_files": d.get("stored_files")}
    keep = False
    for f in ("encrypted_nested_archives", "encrypted_blocked"):
        v = d.get(f) or []
        if v: row[f] = v; keep = True
    for f in ("encrypted_nested_count", "encrypted_blocked_count", "rc2_fatal_accepted", "extract_failure_classification", "error"):
        if d.get(f): row[f] = d[f]; keep = True
    if d.get("extract_diagnostics"):
        row["extract_diagnostics"] = [{x: e.get(x) for x in ("context", "classification", "returncode", "archive") if x in e} for e in d["extract_diagnostics"]][:20]
        keep = True
    if d.get("status") not in ("ok", "complete", "completed", None): keep = True
    return row if keep else None
with ThreadPoolExecutor(8) as ex:
    rows = [r for r in ex.map(one, keys) if r]
s3().put_object(Bucket=B, Key=OUT, Body=json.dumps({"scanned_results": len(keys), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "archives": rows}).encode())
print("archives with leftovers:", len(rows), "->", OUT, flush=True)
