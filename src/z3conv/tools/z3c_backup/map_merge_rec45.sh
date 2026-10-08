#!/bin/bash
# Merge the data-4 files recovered from source archives (/opt/pkgrec4 + /opt/pkgrec5 map_rows.jsonl, S3 SHA-256 proven at upload) into the
# combined proven map written by the data-4 resolver. Writes only cad-disk-extract/_state/packaging/pkg-resolver-d4/.
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PY'
import boto3, json, gzip
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; K = 'cad-disk-extract/_state/packaging/pkg-resolver-d4/disk12_sha_map_all.jsonl.gz'
rows = {}
for l in gzip.decompress(s3.get_object(Bucket=B, Key=K)['Body'].read()).decode().splitlines():
    if l.strip(): x = json.loads(l); rows[x['sha256']] = x
n0 = len(rows); add = 0
for l in [x for f_ in ('/opt/pkgrec4/map_rows.jsonl', '/opt/pkgrec5/map_rows.jsonl') for x in open(f_)]:
    x = json.loads(l)
    if x['sha256'] not in rows and x.get('proof') == 's3_sha256' and x['key'].startswith('cad-disk-extract/'):
        rows[x['sha256']] = x; add += 1
s3.put_object(Bucket=B, Key=K, Body=gzip.compress(''.join(json.dumps(x) + '\n' for x in rows.values()).encode()), ContentType='application/gzip')
print('RESULT map rows', n0, '+ recovered', add, '=', len(rows))
PY
