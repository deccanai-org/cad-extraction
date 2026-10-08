#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/mk_todo.py .
/opt/conv/env/bin/python mk_todo.py 10 3.0
timeout 60 /opt/conv/env/bin/python - <<'PY'
import json, collections
sel = json.load(open('/work/agentwork/sds2-recall-nc1/inv/nc1_sel.json'))
todo = json.load(open('/work/agentwork/sds2-recall-nc1/inv/conv_todo.json'))
mb = sum((sel[j].get('model_bytes') or 0) for j, l in todo)
print('todo model GB', round(mb/1e9, 1))
for j, l in sorted(todo, key=lambda t: -(sel[t[0]].get('holes_kept') or 0))[:60]:
    r = sel[j]
    print(j[:8], l, r['name'][:36], r['labels'], 'MB', round((r.get('model_bytes') or 0)/1e6), 'kept', r['parts_kept'], 'holes', r['holes_kept'], 'ifc', len(r.get('ifc_candidates') or []))
PY
