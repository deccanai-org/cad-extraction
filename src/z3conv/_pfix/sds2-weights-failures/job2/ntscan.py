import json, sys, gzip, boto3, collections, re
s3 = boto3.client("s3", region_name="ap-south-1"); BK = "bim-proprietary-data"
jobs = json.loads(s3.get_object(Bucket=BK, Key="cad-disk-extract/zenitude-data-3/_state/conv/sds2/jobs.json")["Body"].read())
if isinstance(jobs, dict): jobs = jobs.get("jobs", jobs)
byid = {j["id"]: j for j in (jobs if isinstance(jobs, list) else jobs.values())}
out = {}
for jid in open(sys.argv[1]).read().split():
    j = byid.get(jid)
    if not j: out[jid] = "not in jobs.json"; continue
    b = s3.get_object(Bucket=BK, Key=j["files_key"])["Body"].read()
    try: b = gzip.decompress(b)
    except OSError: pass
    fl = json.loads(b)
    dirs = collections.Counter(); subm = 0; idx = []
    for f in fl:
        p = f["p"].replace("\\", "/").split("/")
        dirs[p[0].lower() if len(p) > 1 else "(root)"] += 1
        if len(p) > 1 and p[0].lower() == "subm":
            subm += 1
        if "subm_idx" in f["p"].lower() or "subm_list" in f["p"].lower() or "subm_ctl" in f["p"].lower(): idx.append(f["p"])
    out[jid] = dict(name=j.get("name"), n_files=len(fl), dirs=dict(dirs.most_common(12)), subm_entries=subm, subm_named=idx[:5],
                    paths=j.get("paths", [])[:2], model_bytes=sum(f["size"] for f in fl))
json.dump(out, open(sys.argv[2], "w"), indent=1)
print("ok", len(out))
