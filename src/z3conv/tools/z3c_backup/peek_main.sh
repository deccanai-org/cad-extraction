#!/bin/bash
# READ-ONLY: print the row format of one dataset/main 3d manifest (first rows + one model/ifc and one model/db1 row)
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PYEOF'
import boto3, json
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
pre = [p['Prefix'] for p in s3.list_objects_v2(Bucket=B, Prefix='cad-disk-extract/dataset/main/3d/', Delimiter='/', MaxKeys=40).get('CommonPrefixes', [])]
for p in pre[:40]:
    b = s3.get_object(Bucket=B, Key=p + 'manifest.jsonl')['Body'].read().decode('utf-8', 'replace').splitlines()
    ifc = [l for l in b if 'ifc' in l.lower()][:1]; db1 = [l for l in b if '.db1' in l.lower()][:1]
    if ifc or db1:
        print(p); print('FIRST', b[0][:600]); print('IFC', (ifc or [''])[0][:600]); print('DB1', (db1 or [''])[0][:600])
        print('PJ', s3.get_object(Bucket=B, Key=p + 'project.json')['Body'].read()[:500])
        break
PYEOF
