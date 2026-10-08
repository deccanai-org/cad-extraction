#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PY'
import json, boto3
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; D = 'cad-disk-extract/dataset/packages/'
for pid in ['Zenitude-data-3__Jobs & Data_Files_Completed_On_Server12_Data Files_10.10.40.50_7.331_Data', 'Zenitude-data-3__Jobs & Data_Files_Completed_On_Server12_Jobs Files_FTP Data 19-3-2014_FTP']:
    full = [c['Prefix'] for c in s3.list_objects_v2(Bucket=B, Prefix=D + '3d_partial/' + pid[:60], Delimiter='/').get('CommonPrefixes') or []]
    for fp in full:
        p = fp[len(D + '3d_partial/'):-1]
        r = s3.list_objects_v2(Bucket=B, Prefix=f'{D}3d/{p}/', MaxKeys=3)
        print(p[:100], '| in perfect tier:', r.get('KeyCount', 0) > 0)
PY
grep -n "CANARY" /opt/pkgpartial/loop.log | head -3 | cut -c1-500
