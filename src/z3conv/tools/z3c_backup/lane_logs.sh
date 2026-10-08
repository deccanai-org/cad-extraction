#!/bin/bash
# READ-ONLY: grep the data-3 worker S3 log buffers (fresh heartbeats) for disk-lane / assist start lines; coordinator round log tail.
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PYEOF'
import json, time, collections
import boto3
s3 = boto3.client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
now = time.time(); hits = collections.Counter(); samples = []
for p in ('ifc', 'sds2', 'db1', 'grade'):
    for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=f'{ST}/{p}/logs/'):
        for o in pg.get('Contents', []):
            if now - o['LastModified'].timestamp() > 300:
                continue
            t = s3.get_object(Bucket=B, Key=o['Key'])['Body'].read().decode('utf-8', 'replace').splitlines()
            for l in t:
                if '@zentitude' in l or 'disk lane' in l or 'Traceback' in l or 'Error' in l[:200]:
                    hits[(p, l.split(' ', 1)[-1][:60])] += 1
                    if len(samples) < 12: samples.append(f"{o['Key'].rsplit('/',1)[-1][:40]}: {l[:220]}")
print('hits', dict(hits.most_common(15)))
print('\n'.join(samples))
PYEOF
echo '== coordinator round log'; tail -n 5 /opt/z3c/index.log 2>/dev/null | cut -c1-400; ls -la /opt/z3c/index-*.log 2>/dev/null; tail -n 5 /opt/z3c/index-zentitude-data-4.log 2>/dev/null | cut -c1-600
ps -eo pid,etime,args | grep -E "build_index|coord" | grep -v grep | cut -c1-200
