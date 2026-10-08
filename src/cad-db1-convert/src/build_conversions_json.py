"""Aggregate-only summary of STEP conversions + packaging (no paths/archive names).
Writes conversions.json locally (for the public page) and prints it."""
import json, collections, time, boto3
from concurrent.futures import ThreadPoolExecutor
B = "annotationprod"; R = "cad-disk-extract"
s3 = boto3.Session().client("s3", region_name="ap-south-1")
FINAL = "db1-2026-09-25g"; OLD = ("db1-2026-09-25b", "db1-2026-09-25c", "db1-2026-09-25d", "db1-2026-09-25e")
F_KEEP = {"ok", "empty_model", "no_member_layout", "no_resolvable_members", "bad_output", "deferred_layout", "suspect_orientation", "suspect_attr_link", "convert_error"}
KEEP = {"empty_model", "no_member_layout", "no_resolvable_members", "bad_output", "deferred_layout"}
def keys(pre): return [o["Key"] for pg in s3.get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=pre) for o in pg.get("Contents", [])]
def getj(k):
    for _ in range(4):
        try: return json.loads(s3.get_object(Bucket=B, Key=k)["Body"].read())
        except s3.exceptions.NoSuchKey: return None
        except Exception: time.sleep(1)
jobs = json.loads(s3.get_object(Bucket=B, Key=f"{R}/_control/db1-v2/db1_jobs.json")["Body"].read())["jobs"]
with ThreadPoolExecutor(64) as ex: rs = list(ex.map(lambda j: getj(f"{R}/_state/db1-v2/results/{j['sha']}.json"), jobs))
db1 = []
for j, r in zip(jobs, rs):
    if j["engine"] == "None": db1.append(("no_version_banner", j, None)); continue
    if r and (r.get("code") == FINAL or (r.get("code") == "db1-2026-09-25f" and r.get("status") in F_KEEP) or (r.get("code") in OLD and r.get("status") in KEEP)): db1.append((r["status"], j, r))
    else: db1.append(("pending", j, r))
st = collections.Counter(s for s, _, _ in db1)
by_eng = collections.defaultdict(collections.Counter)
for s, j, _ in db1: by_eng[j["engine"]][s] += 1
ok = [r for s, _, r in db1 if s == "ok"]
ifcjobs = json.loads(s3.get_object(Bucket=B, Key=f"{R}/_control/ifc-step/ifc_jobs.json")["Body"].read()); ifcjobs = ifcjobs["jobs"] if isinstance(ifcjobs, dict) else ifcjobs
with ThreadPoolExecutor(64) as ex: irs = list(ex.map(lambda j: getj(f"{R}/_state/ifc-step/results/{j['id']}.json"), ifcjobs))
ist = collections.Counter((r or {}).get("status", "no_result") for r in irs)
fixes = collections.Counter((r.get("input_unzipped") or r.get("input_fix")) for r in irs if r and r.get("status") == "ok" and (r.get("input_unzipped") or r.get("input_fix")))
ver = [getj(k) for k in keys(f"{R}/_control/packaging/verify/") if k.endswith(".json") and "_of_" in k]
vc = collections.Counter()
for v in ver:
    if v: vc.update(v.get("counts", {}))
out = {
 "schema": "cad-step-conversions/v1", "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
 "db1_to_step": {"scope": "Tekla DB1 models the original converter could not handle (unsupported engine versions + failures), distinct by SHA-256",
   "files": len(jobs), "status": dict(st), "converted_step_files": len(ok),
   "parts_written": sum((r.get("convert") or {}).get("written", 0) for r in ok),
   "by_engine_version": {e: dict(c) for e, c in sorted(by_eng.items())},
   "checks": {"step_ap214_faceted_brep": sum(1 for r in ok if r.get("flavour_ok")),
              "occ_readback_ok": sum(1 for r in ok if (r.get("readback") or {}).get("read_status") == "ok"),
              "occ_readback_skipped_over_64mb": sum(1 for r in ok if (r.get("readback") or {}).get("skipped")),
              "parts_dropped_implausible_profile": sum(((r.get("convert") or {}).get("skipped") or {}).get("implausible_profile", 0) for r in ok),
              "parts_dropped_axis_mismatch": sum((r.get("convert") or {}).get("axis_mismatch_dropped") or 0 for r in ok)},
   "decoder_code": FINAL},
 "ifc_to_step": {"files": len(ifcjobs), "status": dict(ist), "recovered_by_input_fix": dict(fixes)},
 "packaged_dataset": {"verify": dict(vc)},
}
json.dump(out, open("conversions.json", "w"), indent=1)
print(json.dumps(out, indent=1)[:4000])
