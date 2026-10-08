#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PY'
import boto3, json, gzip, collections, random
from concurrent.futures import ThreadPoolExecutor
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zentitude-data-4/_state/conv2'
idx = [json.loads(l) for l in gzip.decompress(s3.get_object(Bucket=B, Key=f'{ST}/index.jsonl.gz')['Body'].read()).splitlines()]
c2 = [r for r in idx if r['pipeline'] == 'ifc' and r.get('class') == 2 and any(i.startswith('parts_outside_volume_tolerance') for i in r.get('issues') or [])]
only = [r for r in c2 if len({i.split(':')[0] for i in r['issues']} | {s['type'] for s in r.get('standins') or []}) == 1]
random.seed(7); smp = random.sample(only, 60)
def one(r):
    try: return r, json.loads(s3.get_object(Bucket=B, Key=f"{ST}/ifc/results/{r['id']}.json")['Body'].read())
    except Exception as e: return r, {'err': str(e)}
kinds = collections.Counter(); rat = collections.Counter(); cls = collections.Counter(); ex = []
with ThreadPoolExecutor(16) as tp:
    for r, res in tp.map(one, smp):
        w = ((res.get('join') or {}).get('volume') or {}).get('worst') or []
        for x in w:
            kinds[x[4]] += 1; cls[x[2]] += 1
            q = x[0]; rat['<0.5' if q < .5 else '0.5-0.9' if q < .9 else '0.9-0.95' if q < .95 else '1.05-1.1' if q < 1.1 else '1.1-2' if q < 2 else '>2'] += 1
        if len(ex) < 6 and w: ex.append((r['id'][:12], r['issues'], w[:4]))
print('RESULT sample', len(smp), 'of only-volume models', len(only))
print('RESULT reference kind of worst parts', kinds.most_common(8))
print('RESULT ratio STEP/expected', rat.most_common()); print('RESULT ifc class', cls.most_common(8))
for e in ex: print('RESULT ex', json.dumps(e)[:600])
PY
