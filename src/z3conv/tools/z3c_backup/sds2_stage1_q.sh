#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PY'
import boto3, json, gzip, collections
from concurrent.futures import ThreadPoolExecutor
s3 = boto3.client('s3'); B = 'bim-proprietary-data'
out = {}
for disk, st in (('data-3', 'cad-disk-extract/zenitude-data-3/_state/conv'), ('data-4', 'cad-disk-extract/zentitude-data-4/_state/conv2')):
    idx = [json.loads(l) for l in gzip.decompress(s3.get_object(Bucket=B, Key=f'{st}/index.jsonl.gz')['Body'].read()).splitlines()]
    s1 = [r for r in idx if r['pipeline'] == 'sds2' and r.get('status') == 'converted_stage1_members_only' and not r.get('reused')]
    def one(r):
        try: return r, json.loads(s3.get_object(Bucket=B, Key=f"{st}/sds2/results/{r['id']}.json")['Body'].read())
        except Exception as e: return r, None
    c = collections.Counter(); q = []
    with ThreadPoolExecutor(32) as tp:
        for r, res in tp.map(one, s1):
            if res is None: c['no_result'] += 1; continue
            rb = ((res.get('manifest') or {}).get('readback') or {}) if isinstance((res.get('manifest') or {}).get('readback'), dict) else {}
            shapes = rb.get('top_level_shapes') or rb.get('valid') or rb.get('solids'); inv = rb.get('invalid')
            reason = res.get('stage2_reason'); c[('reason', reason)] += 1
            if shapes and inv is not None and int(inv) <= max(5, int(0.001 * int(shapes))) and reason == 'invalid_solids':
                q.append(r['id']); c['qualifies'] += 1
            elif shapes is None and reason == 'invalid_solids': c['invalid_solids_no_final_readback'] += 1
    out[disk] = q
    print('RESULT', disk, 'stage-1 rows', len(s1), dict(c))
json.dump(out, open('/opt/pkgd4r4/sds2_stage1_qualify.json', 'w'))
print('RESULT qualify', {k: len(v) for k, v in out.items()})
PY
