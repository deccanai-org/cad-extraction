#!/bin/bash
du -sh /opt/pkgpartial/work/* 2>/dev/null | sort -h | tail -8
ls /opt/pkgpartial/work | wc -l
ps -eo pid,etime,pcpu,rss,args --sort=-pcpu | grep "pkgpartial/loop.py" | grep -v grep | head -5 | cut -c1-120
/opt/conv/env/bin/python - <<'PY'
import json, boto3, datetime
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
L = 'cad-disk-extract/_state/packaging_partial/locks/'
now = datetime.datetime.now(datetime.timezone.utc)
for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=L):
    for o in pg.get('Contents') or []:
        d = json.loads(s3.get_object(Bucket=B, Key=o['Key'])['Body'].read())
        print('lock', o['Key'][len(L):][:70], 'age_min', round((now - o['LastModified']).total_seconds() / 60), d.get('owner', '')[:30])
PY
