#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PY'
import boto3, json, gzip, collections
from concurrent.futures import ThreadPoolExecutor
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; P = 'cad-disk-extract/_state/packaging/unresolved/'
keys = []
for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=P):
    keys += [o['Key'] for o in pg.get('Contents') or []]
def one(k):
    b = s3.get_object(Bucket=B, Key=k)['Body'].read()
    if b[:2] == b'\x1f\x8b': b = gzip.decompress(b)
    return k[len(P):].rsplit('.json', 1)[0], json.loads(b)
out = {}
with ThreadPoolExecutor(32) as tp:
    for pid, d in tp.map(one, keys):
        us = d.get('unresolved_files') or []
        if us: out[pid] = us
c = collections.Counter(); ch = collections.Counter(); why = collections.Counter()
for pid, us in out.items():
    disk = pid.split('__')[0]; c[disk] += len(us)
    for u in us:
        rp = u.get('relpath') if isinstance(u, dict) else str(u)
        ch[(disk, '/'.join(str(rp).split('/')[:2]))] += 1
        if isinstance(u, dict): why[(disk, str(u.get('reason') or u.get('why') or '?')[:40])] += 1
print('RESULT sidecars', len(keys), 'projects with unresolved', len(out), 'files by disk', dict(c))
print('RESULT by channel', ch.most_common(12)); print('RESULT by reason', why.most_common(10))
print('RESULT example', json.dumps(next(iter(out.values()))[0])[:400] if out else None)
json.dump(out, open('/opt/pkgd4r3/unresolved_all.json', 'w'))
PY
