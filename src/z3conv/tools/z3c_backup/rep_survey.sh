#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PY'
import boto3, json, collections
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; P = 'cad-disk-extract/dataset/packages/3d/'
pids = []
for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=P, Delimiter='/'):
    pids += [c['Prefix'][len(P):-1] for c in pg.get('CommonPrefixes') or []]
print('RESULT projects', len(pids), 'data-3', sum(p.startswith('Zenitude-data-3') for p in pids), 'data-4', sum(p.startswith('Zentitude-data-4') for p in pids))
# small sample of manifests: channel dir x modality x role
import random; random.seed(3)
smp = [p for p in pids if p.startswith('Zenitude-data-3')][:4] + random.sample([p for p in pids if p.startswith('Zentitude-data-4')], 4)
c = collections.Counter(); keys = collections.Counter(); ex = {}
for p in smp:
    b = s3.get_object(Bucket=B, Key=f'{P}{p}/manifest.jsonl')['Body'].read().decode('utf-8', 'surrogateescape')
    for l in b.split('\n'):
        if not l.strip(): continue
        r = json.loads(l); ch = '/'.join(r['relpath'].split('/')[:2])
        c[(ch, r.get('modality'), r.get('role'))] += 1; keys.update(r.keys())
        ex.setdefault(ch, r)
for k, v in sorted(c.items()): print('RESULT ch', k, v)
print('RESULT keys', keys.most_common(40))
pj = json.loads(s3.get_object(Bucket=B, Key=f'{P}{smp[0]}/project.json')['Body'].read())
print('RESULT project.json keys', sorted(pj.keys()))
print('RESULT pj sample', json.dumps({k: pj[k] for k in pj if k not in ('unresolved_files',)})[:2500])
print('RESULT step row', json.dumps(ex.get('model/step'))[:800])
PY
