#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
systemctl stop z3pkgp-loop4 2>/dev/null; sleep 3; pkill -f /opt/pkgpartial4/loop.py 2>/dev/null; sleep 2
echo "data-4 loop: $(systemctl is-active z3pkgp-loop4) | data-3 loop: $(systemctl is-active z3pkgp-loop)"
/opt/conv/env/bin/python - <<'PY'
import boto3
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; P = 'cad-disk-extract/_state/packaging_partial/locks/Zentitude-data-4__'
ks = [o['Key'] for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=P) for o in pg.get('Contents') or []]
for k in ks: s3.delete_object(Bucket=B, Key=k)
print('cleared data-4 partial locks', len(ks))
PY
rm -rf /opt/pkgpartial4/work/*; free -g | sed -n 2p
