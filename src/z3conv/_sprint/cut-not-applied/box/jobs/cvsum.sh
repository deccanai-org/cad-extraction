#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/convall_sum.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
/opt/conv/env/bin/python tools/convall_sum.py > res/convall_sum.txt 2>&1; aws s3 cp --quiet res/convall_sum.txt $OUT/convall/convall_sum.txt
grep -A30 "PER ENGINE" res/convall_sum.txt
python3 - <<'P'
import json
rows=[json.loads(l) for l in open('res/convall_sum.txt') if l.startswith('{')]
print('models', len(rows))
for r in rows:
    if r['st'][0] != r['st'][1] or (r['unbuilt'][1] or 0) > 0 or (r['unbuilt'][0] or 0) > 0:
        print(r['id'], r['eng'], 'status', r['st'], 'unbuilt', r['unbuilt'], 'applied', r['applied'], 'cutparts', r['cutparts'], 'written', r['written'])
P
