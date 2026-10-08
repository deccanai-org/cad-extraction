#!/bin/bash
# READ-ONLY: which Zenitude-data-3 archives are byte-identical copies of Disk-2 archives (same relative path + same size; then same name + size).
# Output /opt/report/disk2_in_z3.json (+ pushed to our report prefix)
export AWS_DEFAULT_REGION=ap-south-1
/opt/report/venv/bin/python - <<'PY'
import boto3, json, collections, os
s3 = boto3.client('s3'); B = 'bim-proprietary-data'
ARC = ('.7z', '.zip', '.rar', '.tar', '.gz', '.tgz')
def lst(prefix):
    out = {}
    for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=prefix):
        for o in pg.get('Contents') or []:
            k = o['Key'][len(prefix):]
            if k.lower().endswith(ARC): out[k] = o['Size']
    return out
d2 = lst('Disk-2/'); z3 = lst('Zenitude-data-3/')
print('Disk-2 archives', len(d2), 'data-3 archives', len(z3), flush=True)
exact = {k for k, s in d2.items() if z3.get(k) == s}
byns = collections.defaultdict(list)
for k, s in z3.items(): byns[(k.rsplit('/', 1)[-1], s)].append(k)
rest = {k: s for k, s in d2.items() if k not in exact}
alt = {}
for k, s in rest.items():
    c = byns.get((k.rsplit('/', 1)[-1], s), [])
    if len(c) == 1: alt[k] = c[0]
z3_in_d2 = sorted(exact | set(alt.values()))
unmatched = sorted(set(rest) - set(alt))
print('RESULT exact path+size', len(exact), 'name+size (unique)', len(alt), 'unmatched Disk-2 archives', len(unmatched), 'data-3 archives that are Disk-2', len(z3_in_d2), 'data-3 only', len(z3) - len(z3_in_d2))
print('RESULT unmatched examples', unmatched[:5])
json.dump({'z3_in_d2': z3_in_d2, 'unmatched_d2': unmatched, 'n_d2': len(d2), 'n_z3': len(z3), 'exact': len(exact), 'alt': len(alt)}, open('/opt/report/disk2_in_z3.json', 'w'))
PY
