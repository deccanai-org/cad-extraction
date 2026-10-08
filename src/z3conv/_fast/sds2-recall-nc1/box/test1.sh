#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/ . --exclude "*" --include "*.py" --include "*.sh"
mkdir -p $W/test && cd $W/test
aws s3 cp --quiet "s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/conversions/sds2-step/69da6731bc2432d78a7871ba/v5.1/50_Binney_Sheel_Job_2_69da67_stage2.step" t1.step
timeout 100 /opt/conv/env/bin/python - <<'PY'
import sys, time, collections
sys.path.insert(0, '/work/agentwork/sds2-recall-nc1')
import stepidx, nc1_holes_check as N
t=time.time()
ix = stepidx.index_step('t1.step', log=print)
cc=[c for c in ix['cyl'] if c['concave']]
print('concave cyl', len(cc), 'topo', sum(c['topo'] for c in cc), 'seam', sum(c['seam'] for c in cc))
print('spans', collections.Counter(None if c['span'] is None else round(c['span']) for c in cc).most_common(8))
diag=collections.Counter()
P = N.step_pieces(ix, diag)
print('pieces', len(P), 'with holes', sum(1 for p in P if p['holes']), 'holes', sum(len(p['holes']) for p in P), 'diag', dict(diag))
for p in P:
    if p['holes']: print(p['label'], p['L'], p['W'], p['holes'][:3])
print('labels sample', [l for _,_,l in ix['inst'][:3]])
print('sec', time.time()-t)
PY
