import sys, numpy as np, collections
import ifcopenshell.util.element as ue
exec(open('probe17.py').read().split("st = collections.Counter(); ex = []")[0])
import random; random.seed(2); random.shuffle(pairs)
seen = set()
for e, m in pairs:
    fl = m['prof'].split('/')
    k = (fl[0], fl[6] if len(fl) > 6 else None)
    if k in seen: continue
    seen.add(k)
    V = truthmesh.mesh(e); P = positions(m); z = np.cross(m['x'], m['y'])
    R = V - m['O']; Q = np.stack([R @ m['x'], R @ m['y'], R @ z], 1)
    p = np.array(P[0]); sel = np.linalg.norm(Q[:, :2] - p, axis=1) < float(e.NominalDiameter) / 2 + 0.5
    zs = Q[sel, 2]
    # shank-only vertices: radius ~ d/2
    print(m['prof'], '| L', e.NominalLength, '| mesh z range on axis', round(float(zs.min()), 2), round(float(zs.max()), 2), '| n', len(P))
    if len(seen) > 14: break
