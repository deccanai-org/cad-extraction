#!/bin/bash
cd /work/agentwork/sds2-recall-nc1
timeout 100 /opt/conv/env/bin/python - <<'PY'
import json, glob, sys, hashlib, pickle, numpy as np, collections
sys.path.insert(0, '.')
import sds2_ifc_recall as R, ifc_products
f = sorted(glob.glob('out/ifc/30ff95cd*.json'))[0]
r = json.load(open(f))
F0 = ifc_products.load(f"cache/ifc_{r['ifc_sha256'][:16]}.npz"); F, _ = R.physical_only(F0)
cp = 'cache/step_' + hashlib.sha1(r['step_key'].encode()).hexdigest()[:16] + '.pkl'
ix = pickle.load(open(cp, 'rb')); S = R.step_instances(ix)
hs = [i for i, n in enumerate(S['name']) if n.startswith('HSS10x10') or n.startswith('HSS5x5x1/4')]
print('STEP HSS10x10/HSS5x5x1/4 solids', len(hs), collections.Counter((S['name'][i], S['cls'][i]) for i in hs).most_common(6))
for i in hs[:4]:
    print('  ', S['label'][i][:80], 'center', np.round(S['center'][i]).tolist(), 'ext', np.round(S['ext'][i]).tolist(), 'nv', S['nv'][i])
fj = [j for j, rr in enumerate(F['rows']) if rr[1] == 'IfcColumn' and (rr[4] or '').replace(' ', '').startswith(('HSS10x10', 'HSS5x5x1/4'))]
print('IFC cols', len(fj))
for j in fj[:4]:
    C = S['center']; d = np.linalg.norm(C - F['center'][j], axis=1); k = int(np.argmin(d))
    print('  IFC', F['rows'][j][2], F['rows'][j][4], 'center', np.round(F['center'][j]).tolist(), 'ext', np.round(F['ext'][j]).tolist(), '| nearest STEP', S['label'][k][:60], np.round(S['center'][k]).tolist(), np.round(S['ext'][k]).tolist(), round(float(d[k]), 1))
PY
