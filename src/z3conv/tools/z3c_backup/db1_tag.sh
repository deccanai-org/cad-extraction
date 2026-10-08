#!/bin/bash
# READ-ONLY: the data-3 DB1 rows tagged not_read_back_large_file - current STEP vs the final read-back's STEP, and what the read-back said
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PYEOF'
import json, gzip
import boto3
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
CB = 'annotationprod'
rows = [json.loads(l) for l in gzip.decompress(s3.get_object(Bucket=B, Key=f'{ST}/index.jsonl.gz')['Body'].read()).decode().splitlines() if l.strip()]
def gj(k, b=B):
    try: return json.loads(s3.get_object(Bucket=b, Key=k)['Body'].read())
    except Exception: return None
for r in rows:
    if r['pipeline'] == 'db1' and any('not_read_back_large_file' in str(x) for x in r.get('issues') or []):
        f = gj(f"{ST}/final/results/f-db1-{r['id'][:40]}-readback.json") or {}
        res = gj(f"{ST}/db1/results/{r['id']}.json") or {}
        v = f.get('validate') or {}
        print(r['id'][:16], 'row step', (r.get('step_key') or '')[-40:], '| final step', (f.get('step_key') or '')[-40:], '| final status', f.get('status'),
              'validate keys', sorted(v)[:12], 'skipped', v.get('skipped'), '| result code', res.get('code'), 'res validate skipped', (res.get('validate') or {}).get('skipped'))
fj = gj(f'{ST}/final/jobs.json') or []
print('final jobs', len(fj), 'final_freeze flag', s3.list_objects_v2(Bucket=CB, Prefix='cad-disk-extract/_control/z3conv/coord/final_freeze').get('KeyCount'))
PYEOF
