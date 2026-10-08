#!/bin/bash
# Record results for the data-4 package jobs run by pkg_d4_apply.sh (pkg.py job does not write fleet results), so the coordinator's
# zen4 delta stops treating them as open and emits fresh jobs for unplaced models. Writes ONLY
# bim cad-disk-extract/zenitude-data-3/_state/conv/package/results/<job id>.json for job ids in /opt/pkgd4/jobs that have no result yet.
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PY'
import boto3, json, glob, os, re, datetime, collections
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; RP = 'cad-disk-extract/zenitude-data-3/_state/conv/package/results/'
have = set()
for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=RP):
    have |= {o['Key'].rsplit('/', 1)[-1][:-5] for o in pg.get('Contents') or []}
now = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'); c = collections.Counter()
for jf in sorted(glob.glob('/opt/pkgd4/jobs/*.json')):
    job = json.load(open(jf)); jid = job['id']
    if jid in have: c['already'] += 1; continue
    lf = f'/opt/pkgd4/logs/{jid}.log'
    t = open(lf, errors='replace').read() if os.path.exists(lf) else ''
    i = t.rfind('\n{\n'); j0 = t.find('{\n "project_id"')
    r = None
    for start in ([i + 1] if i >= 0 else []) + ([j0] if j0 >= 0 else []):
        try: r = json.loads(t[start:]); break
        except Exception: pass
    if r is None and 'Traceback' in t:
        m = re.findall(r'^(\w+Error: .*)$', t, re.M)
        r = {'project_id': job['project_id'], 'status': 'fail', 'reason': 'packager_exception', 'error': (m[-1] if m else 'Traceback')[:300]}
    elif r is None and '"status": "partial"' in t:
        st = re.findall(r'^ "status": "(\w+)"', t, re.M)
        r = {'project_id': job['project_id'], 'status': st[-1] if st else 'ok', 'apply': {'status': 'partial',
             'failed_nosuchkey': t.count('NoSuchKey') // 2}, 'note': 'job log truncated by pkg.py job print[:4000]'}
    elif r is None:
        r = {'project_id': job['project_id'], 'status': 'fail', 'reason': 'no_log'}
    r.update(id=jid, pipeline='package', adapter='zen4', finished=now, recorded_by='pkg_d4_apply result backfill (lead, 2026-10-05)')
    s3.put_object(Bucket=B, Key=f'{RP}{jid}.json', Body=json.dumps(r).encode(), ContentType='application/json')
    c[r.get('status')] += 1
    if r.get('status') != 'ok': print('RESULT non-ok', jid, r.get('status'), r.get('reason'), r.get('error'), job['project_id'][:100])
print('RESULT written', dict(c))
PY
