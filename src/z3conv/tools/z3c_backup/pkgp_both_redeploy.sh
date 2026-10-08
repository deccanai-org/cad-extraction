#!/bin/bash
# restart both coordinator partial services on the new kit; clear ONLY the locks this host held (fleet helpers keep theirs)
export AWS_DEFAULT_REGION=ap-south-1
K=/opt/pkgpartial/kit; H=$(hostname)
systemctl stop z3pkgp-loop z3pkgp-loop4 2>/dev/null; sleep 3; pkill -f /opt/pkgpartial/loop.py; pkill -f /opt/pkgpartial4/loop.py; sleep 2
echo "loops: $(systemctl is-active z3pkgp-loop) $(systemctl is-active z3pkgp-loop4)"
/opt/conv/env/bin/python - "$H" <<'PY'
import boto3, json, sys
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; P = 'cad-disk-extract/_state/packaging_partial/locks/'; host = sys.argv[1]; n = keep = 0
for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=P):
    for o in pg.get('Contents') or []:
        try: d = json.loads(s3.get_object(Bucket=B, Key=o['Key'])['Body'].read())
        except Exception: continue
        if d.get('host') == host or (d.get('refresh') and not d.get('host')):
            # refresh writes ({owner, at, refresh}) drop the host: keep them unless the owner job ran here (coordinator logs)
            if d.get('host') == host or __import__('os').path.exists(f"/opt/pkgpartial/logs/{d.get('owner')}.json") or __import__('glob').glob(f"/opt/pkgpartial*/work/{d.get('owner')}"):
                s3.delete_object(Bucket=B, Key=o['Key']); n += 1; continue
        keep += 1
print('cleared coordinator locks', n, 'kept (helpers / others)', keep)
PY
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/package_partial/kit/pkgcore.py $K/pkgcore.py; rm -rf $K/__pycache__
echo "md5 $(md5sum $K/pkgcore.py | cut -c1-32) want 659b0f1de8dbda2222bec8043432e80a"; rm -rf /opt/pkgpartial/work/* /opt/pkgpartial4/work/*
