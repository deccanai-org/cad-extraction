"""After the end-game: put the repaired IFC->STEP conversions into every packaged copy.
Packaged copies were made in IFC round 1 from conversions/ifc-step/<id>.stp; the canonical object has
since been replaced by a repaired conversion (result carries "repair"). For every project whose
manifest row points at that source_key: server-side copy the repaired object over the packaged key,
then update that row's bytes/etag/converter. Rows and project.json slot counts are otherwise unchanged.
  replace_repaired.py            -> dry run (prints what would change)
  replace_repaired.py --apply    -> apply, then re-read every touched row to confirm"""
import json, sys, time, boto3
from botocore.config import Config
B = "annotationprod"; R = "cad-disk-extract"
APPLY = "--apply" in sys.argv
s3 = boto3.Session(profile_name="bim").client("s3", region_name="ap-south-1", config=Config(retries={"max_attempts": 10, "mode": "standard"}, read_timeout=900))
IDS = ["d7fbe72a887216a510f00446bd34a3be_9559427", "ee5b3d7c0d4a5f5c3adf9c7336435e31_8578356",
       "5121a6f954b26cfa73c4a60c9a40ac54_6913063", "4615649aa215295bd13d16f1eb03e9b9_4783717"]
def getj(k): return json.loads(s3.get_object(Bucket=B, Key=k)["Body"].read())
plan = getj(f"{R}/_control/packaging/step_v1_ifc/plan.json")
targets = {}
for p in plan:
    for a in p.get("adds") or []:
        iid = a["out_key"].rsplit("/", 1)[1][:-4]
        if iid in IDS: targets.setdefault(p["project"], []).append((iid, a["name"]))
print("projects to touch:", len(targets), sum(len(v) for v in targets.values()), "rows")
for proj, items in sorted(targets.items()):
    pre = next((f"{R}/dataset/main/{route}/{proj}/" for route in ("3d", "2d") if s3.list_objects_v2(Bucket=B, Prefix=f"{R}/dataset/main/{route}/{proj}/manifest.jsonl").get("KeyCount")), None)
    if pre is None: print("  !! project not found", proj); continue
    mkey = pre + "manifest.jsonl"
    rows = [json.loads(l) for l in s3.get_object(Bucket=B, Key=mkey)["Body"].read().decode().splitlines() if l.strip()]
    changed = 0
    for iid, name in items:
        res = getj(f"{R}/_state/ifc-step/results/{iid}.json")
        if not res.get("repair"): print("  !! result not repaired", iid); continue
        src = f"{R}/conversions/ifc-step/{iid}.stp"; rel = f"model/step/{name}"
        row = next((r for r in rows if r["relpath"] == rel and r.get("source_key") == src), None)
        if row is None: print("  !! row not found", proj, rel); continue
        sh = s3.head_object(Bucket=B, Key=src)
        print(f"  {proj[:70]} {rel}: {row.get('bytes')} -> {sh['ContentLength']}")
        if not APPLY: continue
        dst = pre + rel
        if sh["ContentLength"] > (5 << 30): raise SystemExit("object above 5 GB needs multipart copy")
        s3.copy_object(Bucket=B, Key=dst, CopySource={"Bucket": B, "Key": src}, ContentType="application/step", MetadataDirective="REPLACE")
        dh = s3.head_object(Bucket=B, Key=dst)
        assert dh["ContentLength"] == sh["ContentLength"]
        row["bytes"] = dh["ContentLength"]; row["etag"] = dh["ETag"].strip('"')
        row["converter"] = res.get("converter") or row.get("converter")
        row["repaired"] = "corrupt source coordinates: affected elements tessellated (repair of " + time.strftime("%Y-%m-%d") + ")"
        changed += 1
    if APPLY and changed:
        s3.put_object(Bucket=B, Key=mkey, Body="\n".join(json.dumps(r) for r in rows).encode(), ContentType="application/x-ndjson")
        back = [json.loads(l) for l in s3.get_object(Bucket=B, Key=mkey)["Body"].read().decode().splitlines() if l.strip()]
        assert len(back) == len(rows)
        print("   manifest updated:", changed, "rows")
