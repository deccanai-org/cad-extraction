#!/bin/bash
# stop the partial service (in-flight jobs are idempotent: re-planned next round), clear the partial tier's own job locks, refresh the kit
export AWS_DEFAULT_REGION=ap-south-1
K=/opt/pkgpartial/kit
systemctl stop z3pkgp-loop 2>/dev/null; sleep 3; pkill -f /opt/pkgpartial/loop.py 2>/dev/null; sleep 2
echo "loop: $(systemctl is-active z3pkgp-loop)"
/opt/conv/env/bin/python - <<'PY'
import boto3
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; P = 'cad-disk-extract/_state/packaging_partial/locks/'
ks = [o['Key'] for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=P) for o in pg.get('Contents') or []]
for k in ks: s3.delete_object(Bucket=B, Key=k)      # the partial tier's own lock objects of the stopped jobs
print('cleared partial locks', len(ks))
PY
for f in pkgcore.py pkg.py adapter_zen3.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/package_partial/kit/$f $K/$f; done
rm -rf $K/__pycache__
echo "md5 $(md5sum $K/pkgcore.py $K/pkg.py $K/adapter_zen3.py | cut -c1-32 | tr '\n' ' ')"
echo "want 6432114c98a93f2fc8aa033b77c67537 5d23593a5212ba8cb79bda21492fa7fa b8f15630ec7b504bd07a4f50f3c8dacd"
rm -rf /opt/pkgpartial/work/*
