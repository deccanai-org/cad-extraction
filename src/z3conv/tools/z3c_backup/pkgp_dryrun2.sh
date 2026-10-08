#!/bin/bash
# READ-ONLY partial-tier dry run as a unit (zen4 + summary of the zen3 result already on disk). Log /opt/pkgpartial/out/dryrun.log
export AWS_DEFAULT_REGION=ap-south-1
O=/opt/pkgpartial/out
if systemctl is-active -q z3pkgp-dry; then echo running; tail -n 5 $O/dryrun.log; exit 0; fi
if [ -f $O/dryrun_jobs_zen4.json ]; then echo finished; tail -n 8 $O/dryrun.log; exit 0; fi
cat > $O/dry.py <<'PY'
import json, collections, time, sys; sys.path.insert(0, '/opt/pkgpartial/kit')
import pkg, pkgcore as pc
assert pc.TIER == 'partial'
perfect = set(); tok = None
while True:
    kw = dict(Bucket=pc.BUCKET, Prefix=f'{pc.DATASET}/3d/', Delimiter='/')
    if tok: kw['ContinuationToken'] = tok
    r = pc.s3c().list_objects_v2(**kw); perfect |= {c['Prefix'].split('/')[-2] for c in r.get('CommonPrefixes') or []}
    if not r.get('IsTruncated'): break
    tok = r['NextContinuationToken']
def summ(ad, jobs, st=None):
    tp = {j['project_id'] for j in jobs}
    print('RESULT', ad, 'jobs', len(jobs), 'projects', len(tp), 'also in perfect tier (add-ons)', len(tp & perfect), 'partial-only', len(tp - perfect),
          'steps', sum(len(j.get('add') or []) for j in jobs), 'archive TB', round(sum(j.get('size') or 0 for j in jobs) / 1e12, 2), flush=True)
    if st: print('RESULT', ad, json.dumps({k: st.get(k) for k in ('shipped_models', 'ship_decisions', 'projects_with_shipped_step', 'unknown_archives', 'dedup')}), flush=True)
summ('zen3', json.load(open('/opt/pkgpartial/out/dryrun_jobs_zen3.json')))
t0 = time.time(); jobs, st = pkg.pkg_delta('zen4', write=False)
json.dump(jobs, open('/opt/pkgpartial/out/dryrun_jobs_zen4.json', 'w')); json.dump(st, open('/opt/pkgpartial/out/dryrun_status_zen4.json', 'w'), default=str)
print('zen4 delta s', round(time.time() - t0), flush=True); summ('zen4', jobs, st)
PY
systemd-run --unit=z3pkgp-dry --collect --working-directory=/opt/pkgpartial/kit --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=PKG_TIER=partial \
  --setenv=PKG_PARTIAL_REQUIRE_CODE='{"db1": "z3-db1-2026-10-01v"}' \
  --setenv=PKG_D12MAP=s3://bim-proprietary-data/cad-disk-extract/_state/packaging/pkg-resolver-d4/disk12_sha_map_all.jsonl.gz \
  /bin/bash -c "/opt/conv/env/bin/python $O/dry.py > $O/dryrun.log 2>&1; echo rc=\$? >> $O/dryrun.log"
sleep 20; tail -n 4 $O/dryrun.log
