import json, glob, collections, math, os
import numpy as np
from common import *
D = os.path.join(WORK, 'done', 'piping')
pat = collections.defaultdict(collections.Counter); ratio = collections.defaultdict(list)
def lab(v):
    n = np.linalg.norm(v)
    if n < 2e-3: return 'O'
    v = v / n; i = int(np.argmax(np.abs(v)))
    if abs(v[i]) < 0.95: return 'oblique'
    return ('+' if v[i] > 0 else '-') + 'XYZ'[i]
for f in sorted(glob.glob(D + '/pb*.json')):
    for r in json.load(open(f))['results']:
        if 'error' in r: continue
        J = read_json(os.path.join(OUT, r['json']))
        for C in J['components']:
            M = C.get('matrix')
            if not M or C['pcf_type'] == 'PIPE': continue
            R = np.array([M[0:3], M[3:6], M[6:9]]).T; O = np.array(M[9:12])
            key = []
            for q in C['ports']:
                if q['xyz']:
                    key.append('%d%s' % (q['index'], lab(R.T @ (np.array(q['xyz']) - O))))
            pat[C['pcf_type']][' '.join(key)] += 1
            if C['pcf_type'] in ('VALVE','INSTRUMENT','REDUCER-CONCENTRIC','REDUCER-ECCENTRIC') and C['ep1'] and C['ep2']:
                ratio[C['pcf_type']].append(float(np.linalg.norm(np.array(C['ep1']) + np.array(C['ep2']) - 2 * O)))
for t, c in pat.items():
    print(t, c.most_common(6))
for t, v in ratio.items():
    v = np.array(v); print('midpoint-dev', t, len(v), 'p50 %.4f p95 %.4f max %.4f' % (np.percentile(v, 50), np.percentile(v, 95), v.max()))
