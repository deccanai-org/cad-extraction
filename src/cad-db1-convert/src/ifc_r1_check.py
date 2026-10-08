"""exit 0 when every IFC round-1 project owned by shards FIRST..LAST (of N) has its done marker"""
import json, sys, zlib, boto3
first, last, n = (int(x) for x in sys.argv[1:4])
s3 = boto3.client("s3", region_name="ap-south-1"); B = "annotationprod"; S = "cad-disk-extract/_control/packaging/step_v1_ifc"
plan = json.loads(s3.get_object(Bucket=B, Key=f"{S}/plan.json")["Body"].read())
done = {o["Key"].rsplit("/", 1)[1][:-5] for pg in s3.get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=f"{S}/done/") for o in pg.get("Contents", [])}
mine = [p["project"] for p in plan if first <= zlib.crc32(p["project"].encode()) % n <= last]
left = [p for p in mine if p not in done]
print(f"shards {first}-{last}: {len(mine)} projects, {len(left)} without done marker", flush=True)
sys.exit(0 if not left else 1)
