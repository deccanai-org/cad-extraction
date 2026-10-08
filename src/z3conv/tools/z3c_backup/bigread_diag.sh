#!/bin/bash
# READ-ONLY: data-3 SDS2 rows held at class 2 by not_read_back_large_file - what else holds them, their STEP sizes, and what the final
# pass read-back (step_verify_big) said. Only S3 GET / LIST; writes nothing.
# Run on the coordinator: bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/bigread_diag.sh 200
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PYEOF'
import json, gzip, collections
import boto3
from concurrent.futures import ThreadPoolExecutor
s3 = boto3.client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
rows = [json.loads(l) for l in gzip.decompress(s3.get_object(Bucket=B, Key=f'{ST}/index.jsonl.gz')['Body'].read()).decode().splitlines() if l.strip()]
def tags(r):
    return [x.split(':')[0].split(' (')[0] for x in (r.get('issues') or [])] + [s['type'] for s in r.get('standins') or []] + \
           [x.split(':')[0] for x in (r.get('needs') or [])] + [x.split(':')[0] for x in (r.get('reasons') or [])]
for pipe in ('sds2', 'ifc', 'db1'):
    nr = [r for r in rows if r['pipeline'] == pipe and 'not_read_back_large_file' in tags(r)]
    if not nr:
        continue
    by_cls = collections.Counter(str(r.get('class')) for r in nr)
    only = [r for r in nr if r.get('class') == 2 and set(tags(r)) <= {'not_read_back_large_file', 'class1_pending_verification'}]
    other = collections.Counter()
    for r in nr:
        for t in set(tags(r)) - {'not_read_back_large_file'}:
            other[t] += 1
    sz = sorted((r.get('step_bytes') or 0) for r in nr)
    prim = sum(1 for r in only if r.get('sds2_primary', True))
    print(f'== {pipe}: rows with not_read_back_large_file {len(nr)} by class {dict(by_cls)}; ONLY that tag (would be a class-1 candidate if the '
          f'read-back passes): {len(only)} (sds2 primaries {prim}); STEP GB p50 {sz[len(sz)//2]/1e9:.2f} max {sz[-1]/1e9:.2f}')
    print('   other tags on these rows:', dict(other.most_common(15)))
    def fin(r):
        try:
            return r['id'], json.loads(s3.get_object(Bucket=B, Key=f"{ST}/final/results/f-{pipe}-{r['id'][:40]}-readback.json")['Body'].read())
        except Exception:
            return r['id'], None
    with ThreadPoolExecutor(32) as ex:
        fr = dict(ex.map(fin, nr))
    why = collections.Counter()
    for i, f in fr.items():
        if f is None:
            why['no final read-back result'] += 1; continue
        v = f.get('validate') or f.get('check') or f
        sk = str(v.get('skipped') or v.get('not_verified') or f.get('reason') or f.get('status'))
        why[sk[:70]] += 1
    print('   final read-back outcome:', dict(why.most_common(12)))
    ex_ = [r for r in only][:5]
    for r in ex_:
        print('   e.g.', r['id'][:16], round((r.get('step_bytes') or 0) / 1e9, 2), 'GB', r.get('graded_by'), (fr.get(r['id']) or {}).get('status'))
PYEOF
