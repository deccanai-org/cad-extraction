#!/bin/bash
# READ-ONLY: class-2/3 reasons of the data-4 rows converted so far (disk index), and the DB1 fail reasons
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PYEOF'
import json, gzip, collections
import boto3
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zentitude-data-4/_state/conv2'
rows = [json.loads(l) for l in gzip.decompress(s3.get_object(Bucket=B, Key=f'{ST}/index.jsonl.gz')['Body'].read()).decode().splitlines() if l.strip()]
own = [r for r in rows if not r.get('reused_from_disk') and r.get('class') in (1, 2, 3)]
for p in ('ifc', 'db1', 'sds2'):
    rs = [r for r in own if r['pipeline'] == p]
    c = collections.Counter()
    for r in rs:
        for x in (r.get('issues') or []) + [s_['type'] for s_ in r.get('standins') or []] + (r.get('reasons') or []) + (r.get('needs') or []):
            c[str(x).split(':')[0].split(' (')[0][:40]] += 1
    print(f'== {p}: {len(rs)} graded, classes {dict(collections.Counter(r["class"] for r in rs))}; top tags {dict(c.most_common(14))}')
    for r in rs[:3]:
        print('   e.g.', r['id'][:16], r['class'], r.get('status'), (r.get('issues') or [])[:4], (r.get('reasons') or [])[:3], r.get('graded_by'))
for o in s3.list_objects_v2(Bucket=B, Prefix=f'{ST}/db1/results/').get('Contents', [])[:400]:
    r = json.loads(s3.get_object(Bucket=B, Key=o['Key'])['Body'].read())
    if r.get('status') != 'ok':
        print('DB1 FAIL', o['Key'].rsplit('/', 1)[-1][:16], r.get('reason'), str(r.get('error') or r.get('detail') or '')[:300])
PYEOF
