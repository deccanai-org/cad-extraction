#!/bin/bash
# READ-ONLY dry run of the PARTIAL tier (owner 10-05): kit = the perfect kit (/opt/pkgd4r2/kit) + the tier-switch files from
# _control/z3conv/package_partial/kit/; delta with write=False for data-3 (zen3) and data-4 (zen4). Nothing is written to bim.
export AWS_DEFAULT_REGION=ap-south-1
K=/opt/pkgpartial/kit; mkdir -p $K /opt/pkgpartial/out
cp -a /opt/pkgd4r2/kit/. $K/ && rm -rf $K/__pycache__
for f in pkgcore.py pkg.py adapter_zen3.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/package_partial/kit/$f $K/$f; done
cd $K && PKG_TIER=partial PKG_PARTIAL_REQUIRE_CODE='{"db1": "z3-db1-2026-10-01v"}' \
PKG_D12MAP=s3://bim-proprietary-data/cad-disk-extract/_state/packaging/pkg-resolver-d4/disk12_sha_map_all.jsonl.gz \
timeout 1500 /opt/conv/env/bin/python - <<'PY'
import json, collections, time
import pkg, pkgcore as pc
print('RESULT tier', pc.TIER, 'route', pc.ROUTE, 'state', pc.PSTATE, 'jobs_key', pkg.JOBS_KEY, flush=True)
assert pc.TIER == 'partial' and pc.ROUTE == '3d_partial' and 'packaging_partial' in pc.PSTATE
perfect = set()
tok = None
while True:
    kw = dict(Bucket=pc.BUCKET, Prefix=f'{pc.DATASET}/3d/', Delimiter='/')
    if tok: kw['ContinuationToken'] = tok
    r = pc.s3c().list_objects_v2(**kw); perfect |= {c['Prefix'].split('/')[-2] for c in r.get('CommonPrefixes') or []}
    if not r.get('IsTruncated'): break
    tok = r['NextContinuationToken']
out = {}
for ad in ('zen3', 'zen4'):
    t0 = time.time()
    jobs, st = pkg.pkg_delta(ad, write=False)
    tp = {j['project_id'] for j in jobs}
    out[ad] = {'status': st, 'jobs': len(jobs), 'projects': len(tp), 'also_in_perfect_tier': len(tp & perfect), 'new_partial_only': len(tp - perfect),
               'bytes_hint': sum(j.get('size') or 0 for j in jobs)}
    print('RESULT', ad, round(time.time() - t0), 's', json.dumps({k: st.get(k) for k in ('shipped_models', 'ship_decisions', 'projects_with_shipped_step', 'pending_jobs', 'pending_create', 'pending_steps', 'unknown_archives', 'dedup')}), flush=True)
    print('RESULT', ad, 'projects', len(tp), 'also in perfect tier', len(tp & perfect), 'partial-only', len(tp - perfect), 'archive bytes', round(out[ad]['bytes_hint'] / 1e12, 2), 'TB', flush=True)
    json.dump(jobs, open(f'/opt/pkgpartial/out/dryrun_jobs_{ad}.json', 'w'))
json.dump(out, open('/opt/pkgpartial/out/dryrun.json', 'w'), indent=1, default=str)
PY
