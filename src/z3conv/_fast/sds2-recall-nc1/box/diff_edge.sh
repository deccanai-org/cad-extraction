#!/bin/bash
cd /work/agentwork/sds2-recall-nc1
timeout 110 /opt/conv/env/bin/python - <<'PY'
import json, sys, hashlib, collections, pickle, numpy as np
sys.path.insert(0, '.')
import sds2_ifc_recall as R, ifc_products
Q = json.load(open('inv/ifc_pairs.json'))
o = Q['7699a4a7a0162b6d4ee4eed0']
A = json.load(open('inv/agent_steps.json')).get('7699a4a7a0162b6d4ee4eed0', {})
steps = dict(o['steps']); steps.update(A)
h = [x for x in o['ifc'] if x['sha256'].startswith('a0ae9004')][0]
F0 = ifc_products.load(f"cache/ifc_{h['sha256'][:16]}.npz"); F, exc = R.physical_only(F0)
res = {}
for lab in ('v4c', 'v5.3'):
    e = steps[lab]; cp = 'cache/step_' + hashlib.sha1(e['step'].encode()).hexdigest()[:16] + '.pkl'
    ix = pickle.load(open(cp, 'rb')); S = R.step_instances(ix)
    ms, mf, Cs = R.match(S, F, np.eye(3), np.zeros(3), 25.0)
    res[lab] = (S, ms, mf, Cs)
    print(lab, e['step'][-80:], 'solids', len(S['label']), 'matched', len(ms), collections.Counter(S['cls']).most_common(6))
S4, ms4, mf4, C4 = res['v4c']; S5, ms5, mf5, C5 = res['v5.3']
lost = [j for j in mf4 if j not in mf5]
print('IFC matched by v4c not v5.3:', len(lost), collections.Counter(F['rows'][j][1] + ':' + (F['rows'][j][4] or '') for j in lost).most_common(8))
from collections import Counter
labs4 = Counter(' '.join(S4['label'][mf4[j][0]].split()[:4]) for j in lost)
print('their v4c STEP solids:', labs4.most_common(8))
for j in lost[:5]:
    i4 = mf4[j][0]
    d = np.linalg.norm(C5 - F['center'][j], axis=1); k = int(np.argmin(d))
    print(' IFC', F['rows'][j][1:5], 'ext', np.round(F['ext'][j]).tolist(), '| v4c', S4['label'][i4][:70], np.round(S4['ext'][i4]).tolist(), '| nearest v5.3', S5['label'][k][:90], np.round(S5['ext'][k]).tolist(), round(float(d[k]), 1))
gone = Counter(' '.join(l.split()[2:4]) for l in S4['label']) - Counter(' '.join(l.split()[2:4]) for l in S5['label'])
print('labels present in v4c but fewer in v5.3:', gone.most_common(10))
PY
