#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PY'
import json, boto3
j = json.load(open('/opt/pkgd4/jobs/pkg-c135774e1ae7186e-195604d147.json')); pid = j['project_id']
print('RESULT pid', pid, 'add', len(j.get('add') or []))
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; base = f'cad-disk-extract/dataset/packages/3d/{pid}'
r = s3.list_objects_v2(Bucket=B, Prefix=base + '/', MaxKeys=5); print('RESULT objects(first page)', r.get('KeyCount'), [o['Key'][len(base):] for o in r.get('Contents') or []][:5])
for k in ('manifest.jsonl', 'project.json'):
    try:
        o = s3.get_object(Bucket=B, Key=f'{base}/{k}'); b = o['Body'].read(); print('RESULT', k, len(b), 'bytes; head', repr(b[:400]))
        if k == 'manifest.jsonl':
            bad = 0
            for n, l in enumerate(b.split(b'\n')):
                if not l.strip(): continue
                try: json.loads(l)
                except Exception as e:
                    bad += 1
                    if bad <= 2: print('RESULT bad line', n, e, repr(l[:300]))
            print('RESULT manifest lines', b.count(b'\n'), 'bad', bad)
    except Exception as e: print('RESULT', k, 'ERR', e)
PY
tail -30 /opt/pkgd4/logs/pkg-c135774e1ae7186e-195604d147.log | head -30
