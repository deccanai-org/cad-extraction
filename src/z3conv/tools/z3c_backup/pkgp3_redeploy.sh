#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
K=/opt/pkgpartial/kit
systemctl stop z3pkgp-loop 2>/dev/null; sleep 3; pkill -f /opt/pkgpartial/loop.py 2>/dev/null; sleep 2; echo "data-3 loop: $(systemctl is-active z3pkgp-loop) | data-4 loop: $(systemctl is-active z3pkgp-loop4)"
/opt/conv/env/bin/python - <<'PY'
import boto3
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; P = 'cad-disk-extract/_state/packaging_partial/locks/Zenitude-data-3__'
ks = [o['Key'] for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=P) for o in pg.get('Contents') or []]
for k in ks: s3.delete_object(Bucket=B, Key=k)      # only the stopped data-3 jobs' own locks
print('cleared data-3 partial locks', len(ks))
PY
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/package_partial/kit/pkgcore.py $K/pkgcore.py; rm -rf $K/__pycache__
echo "md5 $(md5sum $K/pkgcore.py | cut -c1-32) want 480d66052c91302c982715fefbff8d02"; rm -rf /opt/pkgpartial/work/*
