#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
{ for v in kitn kitnp7; do python3 -c "
import json; c=json.load(open('pipes5/$v/0762effe61de88c0/convert.json')); k=json.load(open('pipes5/$v/0762effe61de88c0/check.json'))
print('$v', 'written', c.get('written'), 'cuts_applied', c.get('cuts_applied'), 'skipped', {a: b for a, b in (c.get('skipped') or {}).items()}, 'cut_stats', c.get('cut_stats'), 'fittings', c.get('fittings'))
print('   STEP check: roots', k.get('roots'), 'solids', k.get('solids'), 'valid', k.get('valid'), 'invalid', k.get('invalid'), 'nonpos_vol', k.get('nonpos_vol'), 'approx_products', k.get('approx_products'))"; done
PIPE_A=pipes5/kitn PIPE_B=pipes5/kitnp7 /opt/conv/env/bin/python tools/pipe_cmp.py 0762effe61de88c0 2>&1 | python3 -c "
import sys, json
for l in sys.stdin:
    if not l.startswith('{'): print(l[:400]); continue
    r = json.loads(l); rep = r.pop('report', {}) or {}; t = rep.pop('table', None)
    print('pipe_cmp code n -> final:', {k: r[k] for k in r if k not in ('grew_examples',)})
    print('Tekla part list (KSS_part_list.xsr):', rep)
    print('   profile bucket: report n, report kg | code n: n, kg | final: n, kg')
    for row in (t or []): print('   ', row)
"
timeout 900 /opt/conv/ifc84/bin/python tools/hot_fit.py 0762effe61de88c0 pipes5/kitn/0762effe61de88c0 pipes5/kitnp7/0762effe61de88c0 $W/kitnp7 2>&1 | cut -c1-330 | head -3
} > res/final_0762.txt 2>&1
aws s3 cp --quiet res/final_0762.txt $OUT/final/; cat res/final_0762.txt | cut -c1-1500
