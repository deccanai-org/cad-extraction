#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
K=/opt/pkgpartial/kit; H=$(hostname)
systemctl stop z3pkgp-loop 2>/dev/null; sleep 3; pkill -f /opt/pkgpartial/loop.py; sleep 2; echo "data-3 loop: $(systemctl is-active z3pkgp-loop) | data-4 loop: $(systemctl is-active z3pkgp-loop4)"
/opt/conv/env/bin/python - <<'PY'
import boto3, json, os, glob
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; P = 'cad-disk-extract/_state/packaging_partial/locks/Zenitude-data-3__'; n = 0
for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=P):
    for o in pg.get('Contents') or []:
        d = json.loads(s3.get_object(Bucket=B, Key=o['Key'])['Body'].read()); own = d.get('owner')
        if own and (os.path.exists(f'/opt/pkgpartial/work/{own}') or os.path.exists(f'/opt/pkgpartial/logs/{own}.json')):
            s3.delete_object(Bucket=B, Key=o['Key']); n += 1; print('cleared', o['Key'].rsplit('/', 1)[-1][:80])
print('cleared data-3 coordinator locks', n)
PY
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/package_partial/kit/pkgcore.py $K/pkgcore.py; rm -rf $K/__pycache__
echo "md5 $(md5sum $K/pkgcore.py | cut -c1-32) want b4e9893d3ec117c73d7856b30521a459"; rm -rf /opt/pkgpartial/work/*
