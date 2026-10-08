#!/bin/bash
cd /work/agentwork/audit-sds2-v5x
/opt/conv/env/bin/python - <<'PY'
import json, glob, collections, re, os
def lab(c):
    m = re.match(r'z3-sds2-(v[\d.]+?)-2026', str(c or '')); return m.group(1) if m else None
R = [json.load(open(f)) for f in glob.glob('s3/sds2/results/*.json')]
print('results', len(R))
print(collections.Counter((lab(r.get('code')), (r.get('converter') or {}).get('label'), r.get('status')) for r in R).most_common())
alt = [r for r in R if r.get('alternatives')]
print('with alternatives', len(alt), collections.Counter((lab(r.get('code')), (r.get('converter') or {}).get('label'), r.get('chosen'), tuple(sorted(r['alternatives']))) for r in alt).most_common())
keys = collections.Counter(k for r in R for k in r); print(keys.most_common())
ex = next((r for r in alt if r.get('best_of_note')), alt[0] if alt else None)
if ex:
    s = {k: v for k, v in ex.items() if k not in ('log_tail',)}
    print(json.dumps(s, default=str)[:6000])
# output dir structure
lst = collections.Counter()
for d in glob.glob('s3/out/*'):
    b = os.path.basename(d)
    if b == '_not_accepted':
        for d2 in glob.glob(d + '/*'):
            subs = tuple(sorted(os.path.basename(x) for x in glob.glob(d2 + '/*') if os.path.isdir(x)))
            lst[('NA', subs)] += 1
        continue
    subs = tuple(sorted(os.path.basename(x) for x in glob.glob(d + '/*') if os.path.isdir(x)))
    top = any(f.endswith('job.json') for f in os.listdir(d))
    lst[('OK', top, subs)] += 1
for k, v in lst.most_common(): print(v, k)
PY
