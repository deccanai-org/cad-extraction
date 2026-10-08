import sys, numpy as np, collections, random
from bolt853 import *
from raycast import ray_tris
import ifcopenshell, ifcopenshell.geom
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M, seqs, pairs = setup(db1, ifc)
G, _ = db1_guids(db.b); key2g = {v['key']: k for k, v in G.items()}
f = ifcopenshell.open(ifc); tag2e = {(getattr(e, 'Tag', None) or '')[2:38].upper(): e for e in f.by_type('IfcElement')}
st = ifcopenshell.geom.settings(); st.set(st.USE_WORLD_COORDS, True)
r69 = db.bystride[69]; ty = db.I(r69 + 13); b = db.I(r69 + 17); p = db.I(r69 + 21)
rel = collections.defaultdict(list)
for t_, bb, pp in zip(ty, b, p):
    if t_ == 10: rel[int(bb)].append(int(pp))
shapes = {}
def shape(seq):
    if seq in shapes: return shapes[seq]
    g = key2g.get(seq); e = tag2e.get(g)
    r = None
    if e is not None and e.Representation:
        try:
            sh = ifcopenshell.geom.create_shape(st, e); V = np.array(sh.geometry.verts).reshape(-1, 3) * 1000.0; F = np.array(sh.geometry.faces).reshape(-1, 3); r = (V, F)
        except Exception: r = None
    shapes[seq] = r; return r
random.seed(5); sel = [x for x in pairs if classify(positions(db, x[1]), truth_local(*x))[0] == 'exact']; random.shuffle(sel)
res = collections.Counter(); ex = []
for g, m in sel[:250]:
    z = np.cross(m['x'], m['y']); Tl = truth_local(g, m)
    parts = rel.get(m['seq'], [])
    for bi, bt in enumerate(g['bolts'][:1]):
        o = bt['start']; d = -z
        iv = []
        for s in parts:
            sh = shape(s)
            if sh is None: continue
            t = ray_tris(o, d, *sh)
            if len(t) >= 2: iv.append((float(t.min()), float(t.max()), s))
        if not iv: res['no_hit'] += 1; continue
        lo = min(a for a, _, _ in iv); hi = max(b_ for _, b_, _ in iv)
        # in bolt coords: t along -z from head underside; head at t=0 expected at lo
        res[('head_at_first_surface', abs(lo) < 0.6)] += 1
        res[('grip_le_L', hi <= g['L'] + 0.6)] += 1
        if abs(lo) >= 0.6 and len(ex) < 12: ex.append((g['guid'][:8], round(lo, 2), round(hi, 2), 'L', round(g['L'], 1), 'z', round(Tl[bi, 2], 2), [(round(a, 1), round(b_, 1)) for a, b_, _ in iv]))
print(res)
for e in ex: print(e)
