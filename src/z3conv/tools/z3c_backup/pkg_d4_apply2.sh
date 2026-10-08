#!/bin/bash
# Data-4 packaging round 2 (owner-approved data-4 packaging): run the coordinator's current zen4 jobs (jobs_zen4.json: 23 jobs / 78
# models = 49 new class-1 + the 29 of SDS-PROJECTS_81 to 90 whose first job crashed) exactly like a fleet package worker:
# pkg.package_job(job) per job, result -> zenitude-data-3/_state/conv/package/results/<id>.json (minus 'verify' when ok).
# Kit = /opt/pkgd4/kit copy with ONE fix in pkgcore.read_manifest: split on '\n' (str.splitlines also splits on U+2028/U+0085/\x1c..,
# which file names contain -> JSONDecodeError on a valid manifest row). Idempotent: first call starts unit z3pkg-d4apply2.
export AWS_DEFAULT_REGION=ap-south-1
PY=/opt/conv/env/bin/python; D=/opt/pkgd4r2
mkdir -p $D/logs
if [ -f $D/finished ]; then echo "finished $(cat $D/finished)"; cat $D/summary.txt; exit 0; fi
if systemctl is-active -q z3pkg-d4apply2; then echo "running since $(cat $D/started)"; ls $D/logs | wc -l; tail -n 3 $D/driver.log; exit 0; fi
rm -rf $D/kit; cp -r /opt/pkgd4/kit $D/kit
OLD="    return [json.loads(l) for l in d.decode('utf-8', 'surrogateescape').splitlines() if l.strip()]"
NEW="    return [json.loads(l) for l in d.decode('utf-8', 'surrogateescape').split('\\\\n') if l.strip()]   # (lead 10-05) not splitlines(): U+2028 etc. in names"
grep -qxF "$OLD" $D/kit/pkgcore.py || { echo "read_manifest line not found: kit differs, stop"; exit 1; }
$PY - "$D/kit/pkgcore.py" <<'PYF'
import sys
p = sys.argv[1]; t = open(p).read()
old = "    return [json.loads(l) for l in d.decode('utf-8', 'surrogateescape').splitlines() if l.strip()]"
new = "    return [json.loads(l) for l in d.decode('utf-8', 'surrogateescape').split('\\n') if l.strip()]   # (lead 10-05) not splitlines(): U+2028 etc. in names"
assert t.count(old) == 1; open(p, 'w').write(t.replace(old, new))
PYF
grep -n "def read_manifest" -A4 $D/kit/pkgcore.py
aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv/package/jobs_zen4.json $D/jobs_zen4.json
cat > $D/driver.py <<'PYEOF'
import os, sys, json, datetime, collections, traceback
from concurrent.futures import ThreadPoolExecutor
D = '/opt/pkgd4r2'; sys.path.insert(0, f'{D}/kit')
import pkg, pkgcore as pc
RP = 'cad-disk-extract/zenitude-data-3/_state/conv/package/results/'
d = json.load(open(f'{D}/jobs_zen4.json')); jobs = d['jobs'] if isinstance(d, dict) else d
s3 = pc.s3c(); have = set()
for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=pc.BUCKET, Prefix=RP):
    have |= {o['Key'].rsplit('/', 1)[-1][:-5] for o in pg.get('Contents') or []}
todo = [j for j in jobs if j['id'] not in have]
print('jobs', len(jobs), 'todo', len(todo), flush=True)
def one(job):
    try:
        r = pkg.package_job(job, workdir=f'{D}/work/{job["id"]}')
    except Exception as e:
        r = {'project_id': job['project_id'], 'status': 'fail', 'reason': 'packager_exception', 'error': f'{type(e).__name__}: {e}'[:300],
             'trace': traceback.format_exc()[-1500:]}
    json.dump(r, open(f'{D}/logs/{job["id"]}.json', 'w'), indent=1, default=str)
    out = dict(r); out.pop('verify', None) if r.get('status') == 'ok' else None
    out.update(id=job['id'], pipeline='package', adapter='zen4', finished=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
               recorded_by='pkg_d4_apply2 (lead)')
    s3.put_object(Bucket=pc.BUCKET, Key=f'{RP}{job["id"]}.json', Body=json.dumps(out, default=str).encode(), ContentType='application/json')
    print(job['id'], r.get('status'), (r.get('apply') or {}).get('status'), (r.get('verify') or {}).get('checks'), flush=True)
    return r.get('status'), (r.get('apply') or {}).get('status')
with ThreadPoolExecutor(8) as tp:
    res = list(tp.map(one, todo))
open(f'{D}/summary.txt', 'w').write(f"jobs {len(todo)} status {dict(collections.Counter(s for s, _ in res))} apply {dict(collections.Counter(a for _, a in res))}\n")
PYEOF
date -u +%FT%TZ > $D/started
systemctl reset-failed z3pkg-d4apply2 2>/dev/null
systemd-run --unit=z3pkg-d4apply2 --collect --nice=5 --working-directory=$D/kit --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=PKG_ALLOW_WRITE=1 /bin/bash -c \
  "$PY $D/driver.py > $D/driver.log 2>&1; echo rc=\$? >> $D/driver.log; date -u +%FT%TZ > $D/finished"
sleep 15; echo "started: $(systemctl is-active z3pkg-d4apply2)"; tail -n 3 $D/driver.log
