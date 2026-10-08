#!/bin/bash
# Data-4 packaging round 3: the coordinator's current zen4 jobs (12: 11 stale re-emits of models already placed = no-op updates, 1 real add
# for the E-Drive project whose round-2 job hit a transient SSL error). Same driver / kit / result recording as round 2 (pkg_d4_apply3.sh).
export AWS_DEFAULT_REGION=ap-south-1
PY=/opt/conv/env/bin/python; D=/opt/pkgd4r4
mkdir -p $D/logs
if [ -f $D/finished ]; then echo "finished $(cat $D/finished)"; cat $D/summary.txt; grep -v "^jobs" $D/driver.log | cut -c1-250; exit 0; fi
if systemctl is-active -q z3pkg-d4apply4; then echo "running since $(cat $D/started)"; grep -c " ok \| fail " $D/driver.log; tail -n 4 $D/driver.log | cut -c1-250; exit 0; fi
aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv/package/jobs_zen4.json $D/jobs_zen4.json; echo "jobs: $($PY -c "import json;d=json.load(open('$D/jobs_zen4.json'));print(len(d['jobs'] if isinstance(d,dict) else d))")"
cat > $D/driver.py <<'PYEOF'
import os, sys, json, datetime, collections, traceback, time
from multiprocessing import Pool
D = '/opt/pkgd4r4'; sys.path.insert(0, '/opt/pkgd4r2/kit')
import pkg, pkgcore as pc
RP = 'cad-disk-extract/zenitude-data-3/_state/conv/package/results/'
def one(job):
    s3 = pc.s3c()
    for attempt in range(20):
        try:
            r = pkg.package_job(job, workdir=f'{D}/work/{job["id"]}')
        except Exception as e:
            r = {'project_id': job['project_id'], 'status': 'fail', 'reason': 'packager_exception', 'error': f'{type(e).__name__}: {e}'[:300],
                 'trace': traceback.format_exc()[-1500:]}
        if r.get('status') == 'retry' and r.get('reason') == 'project_locked':
            time.sleep(60); continue
        break
    json.dump(r, open(f'{D}/logs/{job["id"]}.json', 'w'), indent=1, default=str)
    out = dict(r); out.pop('verify', None) if r.get('status') == 'ok' else None
    out.update(id=job['id'], pipeline='package', adapter='zen4', finished=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
               recorded_by='pkg_d4_apply4 (lead)')
    if r.get('status') != 'retry':
        s3.put_object(Bucket=pc.BUCKET, Key=f'{RP}{job["id"]}.json', Body=json.dumps(out, default=str).encode(), ContentType='application/json')
    print(job['id'], r.get('status'), r.get('reason'), (r.get('apply') or {}).get('status'), (r.get('verify') or {}).get('checks'), flush=True)
    return r.get('status'), (r.get('apply') or {}).get('status')
if __name__ == '__main__':
    d = json.load(open('/opt/pkgd4r4/jobs_zen4.json')); jobs = d['jobs'] if isinstance(d, dict) else d
    s3 = pc.s3c(); have = set()
    for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=pc.BUCKET, Prefix=RP):
        have |= {o['Key'].rsplit('/', 1)[-1][:-5] for o in pg.get('Contents') or []}
    todo = sorted([j for j in jobs if j['id'] not in have], key=lambda j: -(j.get('size') or 0))
    print('jobs', len(jobs), 'todo', len(todo), flush=True)
    with Pool(12, maxtasksperchild=1) as pool:
        res = list(pool.imap_unordered(one, todo))
    open(f'{D}/summary.txt', 'w').write(f"jobs {len(todo)} status {dict(collections.Counter(s for s, _ in res))} apply {dict(collections.Counter(a for _, a in res))}\n")
PYEOF
date -u +%FT%TZ > $D/started
systemctl reset-failed z3pkg-d4apply4 2>/dev/null
systemd-run --unit=z3pkg-d4apply4 --collect --nice=5 --working-directory=/opt/pkgd4r2/kit --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=PKG_ALLOW_WRITE=1 --setenv=PKG_LOCK_STALE_S=420 /bin/bash -c \
  "$PY $D/driver.py > $D/driver.log 2>&1; echo rc=\$? >> $D/driver.log; date -u +%FT%TZ > $D/finished"
sleep 20; echo "started: $(systemctl is-active z3pkg-d4apply4)"; tail -n 3 $D/driver.log
