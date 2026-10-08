#!/bin/bash
# READ-ONLY: data-3 SDS2 results published as stage 1 with stage2_reason invalid_solids - is the stage-2 STEP stored (under
# _not_accepted/) and does the converter manifest's FINAL read-back (after repair) say every shape valid? Only S3 GET / LIST.
# Run on the coordinator: bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/sds2_qa_diag.sh 300
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PYEOF'
import json, collections
import boto3
from concurrent.futures import ThreadPoolExecutor
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
for tag, ST, OUT in (('data-3', 'cad-disk-extract/zenitude-data-3/_state/conv/sds2', 'cad-disk-extract/zenitude-data-3/conversions/sds2-step'),
                     ('data-4', 'cad-disk-extract/zentitude-data-4/_state/conv2/sds2', 'cad-disk-extract/zentitude-data-4/conversions/sds2-step')):
    keys = []
    for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=f'{ST}/results/'):
        keys += [o['Key'] for o in pg.get('Contents', []) if o['Key'].endswith('.json')]
    def one(k):
        try: return json.loads(s3.get_object(Bucket=B, Key=k)['Body'].read())
        except Exception: return None
    with ThreadPoolExecutor(64) as ex:
        res = [r for r in ex.map(one, keys) if r]
    cand = [r for r in res if r.get('status') == 'ok_stage1' and r.get('stage2_reason') == 'invalid_solids']
    c = collections.Counter(); ex_ = []
    def chk(r):
        rbm = ((r.get('manifest') or {}).get('readback') or {})
        rep = bool((r.get('manifest') or {}).get('readback_repair')); cnt = ((r.get('manifest') or {}).get('counts') or {})
        pre = (r.get('outputs') or {}).get('prefix') or ''
        na = None
        jid = r.get('id') or ''
        try:
            lo = s3.list_objects_v2(Bucket=B, Prefix=f"{OUT}/_not_accepted/{jid}", MaxKeys=50).get('Contents', [])
            na = [o['Key'] for o in lo if o['Key'].endswith('_stage2.step')]
        except Exception:
            na = None
        return r, rbm, rep, cnt, na
    with ThreadPoolExecutor(32) as ex:
        for r, rbm, rep, cnt, na in ex.map(chk, cand):
            inv = rbm.get('invalid'); allv = (inv == 0) if inv is not None else None
            tl = rbm.get('top_level_shapes') or rbm.get('solids') or 0
            thr = max(5, int(0.001 * (rbm.get('solids') or 0)))
            if inv is not None and inv > 0:
                c['  invalid>0 within the publish threshold max(5, 0.1%)' if inv <= thr else '  invalid>0 above the threshold'] += 1
            r12 = (r.get('stage2') or {}); c[f"  log-first-block bad={max(0, (r12.get('with_solids') or 0) - (r12.get('brep_valid') or 0)) > thr}"] += 0
            k = ('stage2_stored' if na else 'no_stage2_stored') + '|' + ('final_readback_all_valid' if allv else ('final_readback_invalid>0' if allv is False else 'no_invalid_field')) + \
                ('|repair' if rep else '') + ('|reference' if (r.get('manifest') or {}).get('reference_model') else '')
            c[k] += 1
            if len(ex_) < 4 and allv and na:
                ex_.append((r.get('id'), rbm, cnt.get('invalid_parts_excluded'), na[0][-60:]))
    print(f'== {tag}: results {len(res)}, ok_stage1 with stage2_reason invalid_solids: {len(cand)}')
    for k, v in c.most_common():
        print('  ', v, k)
    for e in ex_:
        print('   e.g.', e[0], json.dumps(e[1])[:300], 'excluded', e[2], e[3])
PYEOF
