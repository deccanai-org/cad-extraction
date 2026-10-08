#!/bin/bash
echo "worker procs: $(pgrep -fc 'pkgpartial/loop.py')"; ls /opt/pkgpartial/work/ | wc -l
/opt/conv/env/bin/python - <<'PY'
import boto3, collections
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'; P = 'cad-disk-extract/dataset/packages/3d_partial/'
n = 0; b = 0
for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=P):
    for o in pg.get('Contents') or []: n += 1; b += o['Size']
print('objects', n, 'GB', round(b / 1e9, 1))
PY
