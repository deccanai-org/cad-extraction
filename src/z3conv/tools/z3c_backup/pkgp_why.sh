#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
cd /opt/pkgpartial/kit && /opt/conv/env/bin/python - <<'PY'
import json, sys
sys.path.insert(0, '/opt/pkgpartial/kit')
import os; os.environ['PKG_TIER'] = 'partial'
import pkgcore as pc
pid = 'Zenitude-data-3__Completed_Jobs_Data_SDS_Jobs_2017.19_GEM BUILDINGS_VIOLET STREET'
r = pc.s3c().list_objects_v2(Bucket=pc.BUCKET, Prefix=f'{pc.PSTATE}/plans/')
ks = [o['Key'] for o in r.get('Contents') or [] if 'GEM BUILDINGS_VIOLET' in o['Key']]
print('plans', ks)
for k in ks:
    p = pc.get_json(pc.BUCKET, k)
    print('status', p['status'], 'stats', json.dumps(p['stats'])[:400])
    for x in p['steps_not_shipped'][:6]: print('NS', json.dumps(x)[:300])
    print('unresolved', len(p.get('unresolved_files') or []), [ (u.get('path') or '')[-80:] for u in (p.get('unresolved_files') or [])[:3]])
PY
