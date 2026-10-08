#!/bin/bash
W=/work/agentwork/ifc-verification-residue
cd $W/diag/gp
python3 - <<'PY'
import json, glob, os
for fn in sorted(glob.glob('*.far.json')):
    n = fn[:-9]
    try:
        a = json.load(open(n + '.stock.json')); b = json.load(open(fn))
    except Exception as e:
        print(n, 'incomplete', e); continue
    k = ('transferred', 'solids', 'valid', 'invalid', 'nonpos_vol', 'faces')
    print(n, 'stock', {x: a.get(x) for x in k}, '| far', {x: b.get(x) for x in k}, 'off', b.get('translated_for_check_mm'), 'bbox_equal', a.get('bbox') == b.get('bbox'))
PY
