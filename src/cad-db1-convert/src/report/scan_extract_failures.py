"""Scan every extraction result (EC2 era) and keep only what could NOT be opened / read:
encrypted top-level members, password-protected nested archives, 7-Zip rc=2 fatal errors
accepted as partial success, depth-cap hits and failure diagnostics.
-> s3://annotationprod/cad-disk-extract/_control/reports/extraction_failures.jsonl"""
import json, boto3, threading, sys, time
from concurrent.futures import ThreadPoolExecutor
from botocore.config import Config
B = "annotationprod"; P = "cad-disk-extract/_state/ec2-results/"
sess = boto3.Session(); tl = threading.local()
def s3():
    c = getattr(tl, "c", None)
    if c is None: c = tl.c = sess.client("s3", region_name="ap-south-1", config=Config(max_pool_connections=64, retries={"max_attempts": 10, "mode": "adaptive"}))
    return c
keys = [o["Key"] for pg in s3().get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=P) for o in pg.get("Contents", []) if o["Key"].endswith(".json")]
print("results", len(keys), flush=True)
def one(k):
    r = json.loads(s3().get_object(Bucket=B, Key=k)["Body"].read())
    diag = [{"context": d.get("context"), "classification": d.get("classification"), "returncode": d.get("returncode"),
             "stderr_tail": (d.get("stderr_tail") or "")[-600:]} for d in (r.get("extract_diagnostics") or [])]
    return {"source_key": r.get("source_key"), "disk": r.get("disk"), "status": r.get("status"), "archive_bytes": r.get("archive_bytes"),
            "stored_files": r.get("stored_files"), "encrypted_blocked_count": r.get("encrypted_blocked_count", 0),
            "encrypted_blocked": r.get("encrypted_blocked") or [], "encrypted_nested_count": r.get("encrypted_nested_count", 0),
            "encrypted_nested_archives": r.get("encrypted_nested_archives") or [], "rc2_fatal_accepted": r.get("rc2_fatal_accepted", 0),
            "extract_failure_classification": r.get("extract_failure_classification"), "extract_diagnostics": diag,
            "depth_cap_hits": r.get("depth_cap_hits", 0), "max_depth_seen": r.get("max_depth_seen"), "retries": r.get("retries", 0),
            "finished_at": r.get("finished_at")}
t = time.time()
with ThreadPoolExecutor(24) as ex: rows = list(ex.map(one, keys))
body = "\n".join(json.dumps(x) for x in rows).encode()
s3().put_object(Bucket=B, Key="cad-disk-extract/_control/reports/extraction_failures.jsonl", Body=body)
print("done", len(rows), round(time.time() - t), "s", flush=True)
