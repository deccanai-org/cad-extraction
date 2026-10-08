"""Stage SDS2 ground truth for adapter_sds2.py --gt-dir: IFC export / KISS / NC1 files stored under the SDS2 job folder
in the source (same storage roots as the job's model files). The fleet's files manifest stages model files only.

usage: python stage_gt.py --id <24-hex job id> --dest <dir>     (bucket bim-proprietary-data, default AWS credentials)
prints the counts; exits 0 with an empty dest when the job folder holds none (then call the adapter without --gt-dir).
Files keep their path below the job folder; extensions are lower-cased (the verifier globs '*.nc1' / '*.kss').
"""
import os, sys, json, gzip, argparse
import boto3
B = "bim-proprietary-data"; STATE = "cad-disk-extract/zenitude-data-3/_state/conv/sds2/"
EXT = {".ifc": "ifc", ".kss": "kss", ".nc1": "nc1"}
ap = argparse.ArgumentParser(); ap.add_argument("--id", required=True); ap.add_argument("--dest", required=True)
ap.add_argument("--max", type=int, default=2000)
a = ap.parse_args()
s3 = boto3.client("s3", region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-south-1"))
lst = s3.list_objects_v2(Bucket=B, Prefix=f"{STATE}files/{a.id}").get("Contents") or []
if not lst:
    sys.exit(f"no files manifest for {a.id}")
body = s3.get_object(Bucket=B, Key=lst[0]["Key"])["Body"].read()
try:
    body = gzip.decompress(body)
except OSError:
    pass
mf = json.loads(body)
roots = sorted({f["key"][:-len(f["p"])] for f in mf if f.get("key") and f["key"].endswith(f["p"])})[:4]
n = {"ifc": 0, "kss": 0, "nc1": 0}
for root in roots:
    for pg in s3.get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=root):
        for o in pg.get("Contents", []):
            ext = os.path.splitext(o["Key"])[1].lower()
            if ext in EXT and n[EXT[ext]] < a.max:
                p = os.path.join(a.dest, os.path.splitext(o["Key"][len(root):])[0] + ext)
                if not os.path.exists(p):
                    os.makedirs(os.path.dirname(p), exist_ok=True); s3.download_file(B, o["Key"], p); n[EXT[ext]] += 1
print(json.dumps(dict(id=a.id, roots=len(roots), **n)))
