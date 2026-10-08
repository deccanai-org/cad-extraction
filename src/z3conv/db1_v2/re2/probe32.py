import sys, os, numpy as np, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, '/work/agentwork/db1v2-val/code')
from cache import get
from guid2 import guid_keys
import ifcbolts
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
G, back, top = guid_keys(db); B, GR = ifcbolts.bolts(ifc, True)
P = pts[lay.get('pts', 0)]
C = next((c for c in cs if c['stride'] == lay.get('csys_stride') and c['k'] == lay.get('csys_k') and c['key'] == lay['csys_key']), None)
hmap = {}
for s_, recs_ in db.runs:
    if s_ < 33 or s_ % 33: continue
    a = db.I(recs_ + 13); ao = db.lookup(a); ob = np.where(ao >= 0, db.I(np.where(ao >= 0, ao, 0) + 13), -1)
    for o in recs_[ob == 10]: hmap.setdefault(int(db.I([o + 9])[0]), int(o))
def placement(k):
    for o in db.lookup_all(k):
        c_ = int(db.I([o + 13])[0])
        if c_ in C['map']:
            X = db.D(o + 17 + 8 * np.arange(4))
            if np.all(np.isfinite(X)) and np.all(np.abs(X[:3]) < 1e8) and X[3] > 0: return o
n = 0; nomap = collections.Counter()
for g in GR:
    k = G.get(g['guid'])
    if k not in hmap:
        ss = tuple(sorted(int(s) for s, (K, O) in db.seqidx.items() if np.searchsorted(K, k or -1, 'right') > np.searchsorted(K, k or -1, 'left')))
        nomap[ss] += 1; continue
    if len(g['bolts']) < 3: continue
    h = hmap[k]; po = placement(k)
    if po is None: continue
    O = db.D(po + 17 + 8 * np.arange(3)); x, y = C['map'][int(db.I([po + 13])[0])]; y = y - (y @ x) * x; y /= np.linalg.norm(y)
    p1 = db._pt(P, db.I([h + 21]))[0]; p2 = db._pt(P, db.I([h + 25]))[0]
    Lr = (p2 - p1) @ x; t0 = (O - p1) @ x; sgn = 1 if abs(t0) <= abs(t0 - Lr) else -1; x = sgn * x; z = np.cross(x, y)
    T = np.array([[(b['start'] - O) @ x, (b['start'] - O) @ y] for b in g['bolts']])
    pk = int(db.I([h + 29])[0]); r0 = db.lookup_all(pk)[0]; S = int(db.lookup_stride([pk])[0])
    print('\nGUID', g['guid'][:8], 'n', len(g['bolts']), 'S', S, 'truth uv', np.round(T, 2).tolist())
    F = db.F(r0 + np.arange(9, S - 3, 4)); I = db.I(r0 + np.arange(9, S - 3, 4))
    print('  floats', [(9 + 4 * i, round(float(v), 2)) for i, v in enumerate(F) if np.isfinite(v) and 1e-3 < abs(v) < 1e6])
    print('  INT_MAX at', [9 + 4 * i for i, v in enumerate(I) if v == 2147483647])
    n += 1
    if n >= 3: break
print('no header for GUID keys -> strides', nomap.most_common(6))
