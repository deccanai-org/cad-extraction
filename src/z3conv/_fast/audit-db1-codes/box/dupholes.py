"""dupholes.py [KIT]: per part, pairs of bolt holes that are coaxial (axes parallel within 1e-3 rad, axis distance < 1 mm):
identical (< 0.01 mm) or near-coincident (0.01-1 mm) cylinders. Near-coincident pairs make OpenCASCADE's boolean fail
(deployed .i: 11/11 L4-surface parts are fixed by dropping one hole of such a pair)."""
import json, os, sys, glob, collections
import numpy as np
W = os.path.dirname(os.path.abspath(__file__)); os.chdir(W)
KIT = sys.argv[1] if len(sys.argv) > 1 else 'jfix_audit2'
T = collections.Counter(); per = {}; ex = []
for ap in sorted(glob.glob(f'dec/{KIT}/*.audit.json')):
    i = os.path.basename(ap)[:-11]; A = json.load(open(ap))
    byp = collections.defaultdict(list)
    for b in A['bolts']:
        for p in b['hits']:
            byp[p].append(b)
    c = collections.Counter()
    for p, bl in byp.items():
        if len(bl) < 2: continue
        C = np.array([b['c'] for b in bl]); E = np.array([b['ez'] for b in bl]); D = np.array([float(b.get('d_stored') or b['d']) for b in bl])
        for a in range(len(bl)):
            par = np.abs(E[a + 1:] @ E[a]) > 1 - 5e-7
            if not par.any(): continue
            w = C[a + 1:] - C[a]; perp = w - (w @ E[a])[:, None] * E[a][None, :]; dist = np.linalg.norm(perp, axis=1)
            for k in np.nonzero(par & (dist < 1.0))[0]:
                bb = bl[a + 1 + k]; same_g = bb['gid'] == bl[a]['gid']
                kind = 'identical' if dist[k] < 0.01 else 'near'
                c[kind + ('_same_group' if same_g else '_other_group')] += 1
                if kind == 'near' and len(ex) < 12:
                    ex.append({'id': i[:12], 'part': p, 'prof': A['parts'].get(str(p), {}).get('prof'), 'dist_mm': round(float(dist[k]), 3),
                               'groups': [bl[a]['gid'], bb['gid']], 'd': [D[a], D[a + 1 + k]]})
        if any(c.values()): pass
    parts_aff = sum(1 for p, bl in byp.items() if len(bl) > 1)
    if c: per[i] = dict(c)
    for k, v in c.items(): T[k] += v
    T['models'] += 1; T['models_with_near'] += 1 if (c.get('near_same_group', 0) + c.get('near_other_group', 0)) else 0
json.dump({'kit': KIT, 'totals': dict(T), 'per_model': per, 'examples': ex}, open(f'report/dupholes_{KIT}.json', 'w'), indent=1)
print(json.dumps({'totals': dict(T), 'examples': ex[:6]}, indent=1))
