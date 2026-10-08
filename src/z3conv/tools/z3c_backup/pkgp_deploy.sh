#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
K=/opt/pkgpartial/kit
systemctl is-active -q z3pkgp-loop && { echo "loop still active: abort"; exit 1; }
for f in pkgcore.py pkg.py adapter_zen3.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/package_partial/kit/$f $K/$f; done
rm -rf $K/__pycache__; echo "kit md5 $(md5sum $K/pkgcore.py | cut -c1-32) expected a81cbe9195add8364ef1a84fbd93fa0c"
grep -c "from_perf" $K/pkgcore.py
/opt/conv/env/bin/python - <<'PY'
import json, boto3
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; D = 'cad-disk-extract/dataset/packages/'
P = D + '3d_partial/'
for c in s3.list_objects_v2(Bucket=B, Prefix=P, Delimiter='/').get('CommonPrefixes') or []:
    pid = c['Prefix'][len(P):-1]
    if s3.list_objects_v2(Bucket=B, Prefix=f'{D}3d/{pid}/', MaxKeys=1).get('KeyCount', 0):
        k = f'{P}{pid}/project.json'; pj = json.loads(s3.get_object(Bucket=B, Key=k)['Body'].read())
        if not pj.get('addon_of'):
            pj['addon_of'] = f'{D}3d/{pid}'
            pj['sources'] = 'in the perfect package (addon_of): only partial STEP files (and SDS2 job zips the perfect package lacks) are here'
            s3.put_object(Bucket=B, Key=k, Body=json.dumps(pj, indent=1, ensure_ascii=False).encode(), ContentType='application/json')
            print('marked add-on', pid[:90])
PY
rm -f /opt/pkgpartial/canary_fail
