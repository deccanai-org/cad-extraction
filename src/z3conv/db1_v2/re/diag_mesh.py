import sys, numpy as np, ifcopenshell
from cache import *
from guid2 import guid_keys
from db1bolts2 import BoltDecoder
import truthmesh
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
bd = BoltDecoder(db, pts, cs, lay); G = bd.decode(M); bys = {g['seq']: g for g in G}
GK, back, top = guid_keys(db)
f = ifcopenshell.open(ifc)
for e in f.by_type('IfcMechanicalFastener')[:6]:
    g = bys.get(GK.get((e.Tag or '')[2:38].upper()))
    if g is None: continue
    V = truthmesh.mesh(e); R = V - g['O']
    Q = np.stack([R @ g['x'], R @ g['y'], R @ g['z']], 1)
    print(g['prof'] if 'prof' in g else '', 'uv', np.round(g['uv'], 1).tolist(), '| mesh xy range', np.round(Q[:, 0].min(), 1), np.round(Q[:, 0].max(), 1), np.round(Q[:, 1].min(), 1), np.round(Q[:, 1].max(), 1), 'z', np.round(Q[:, 2].min(), 1), np.round(Q[:, 2].max(), 1))
    C = truthmesh.centres(V, g['O'], g['x'], g['y'], float(e.NominalDiameter), cell=float(e.NominalDiameter) * 0.5)
    print('    centres', [tuple(np.round(c[:2], 1)) for c in C][:8])
