"""8.85/9.08 composite bolt groups: header(33: attr@13 csys?@17 p1@21 p2@25 pattern@29) + placement(49: csys@13 O@17 L@41).
Validate positions vs IFC truth; detect the pattern-record array layout per stride."""
import sys, os, numpy as np, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, '/work/agentwork/db1v2-val/code')
from cache import get
from guid2 import guid_keys
from db1dec import inkeys
import ifcbolts
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
P = pts[lay.get('pts', 0)]
C = next((c for c in cs if c['stride'] == lay.get('csys_stride') and c['k'] == lay.get('csys_k') and c['key'] == lay['csys_key']), None)
print('csys table', C['stride'], C['k'], C['key'], len(C['keys']), 'all csys tables', [(c['stride'], c['k'], c['key'], len(c['keys'])) for c in cs])
G, back, top = guid_keys(db)
B, GR = ifcbolts.bolts(ifc, True)
hmap = {}; hs_ = collections.Counter()
for s_, recs_ in db.runs:
    if s_ < 33 or s_ % 33: continue
    a = db.I(recs_ + 13); ao = db.lookup(a); ob = np.where(ao >= 0, db.I(np.where(ao >= 0, ao, 0) + 13), -1)
    for o in recs_[ob == 10]: hmap.setdefault(int(db.I([o + 9])[0]), int(o)); hs_[s_] += 1
print('bolt headers', len(hmap), 'by run stride', hs_.most_common(5))
def placement(k):
    for o in db.lookup_all(k):
        c_ = int(db.I([o + 13])[0])
        if c_ in C['map']:
            X = db.D(o + 17 + 8 * np.arange(4))
            if np.all(np.isfinite(X)) and np.all(np.abs(X[:3]) < 1e8) and X[3] > 0: return o
    return None
plk = None
stat = collections.Counter(); exa = []
lay_try = {}
for g in GR:
    k = G.get(g['guid'])
    if k is None or k not in hmap or not g['bolts']: stat['no_header'] += 1; continue
    h = hmap[k]
    po = placement(k)
    if po is None: stat['no_placement'] += 1; continue
    po = int(po); cref = int(db.I([po + 13])[0])
    O = db.D(po + 17 + 8 * np.arange(3)); L = float(db.D([po + 41])[0])
    p1 = db._pt(P, db.I([h + 21]))[0]; p2 = db._pt(P, db.I([h + 25]))[0]
    hc = int(db.I([h + 17])[0])
    inC = cref in C['map']; inC2 = hc in C['map']
    stat[('csys@49.13 in map', inC)] += 1; stat[('csys@33.17 in map', inC2)] += 1
    if not inC:
        continue
    x, y = C['map'][cref]; y = y - (y @ x) * x; y = y / np.linalg.norm(y)
    Lr = (p2 - p1) @ x; t0 = (O - p1) @ x; sgn = 1 if abs(t0) <= abs(t0 - Lr) else -1
    x = sgn * x; z = np.cross(x, y)
    T = np.array([[(b['start'] - O) @ x, (b['start'] - O) @ y, (b['start'] - O) @ z] for b in g['bolts']])
    stat[('axis_minus_z', all(b['axis'] @ z < -0.999 for b in g['bolts']))] += 1
    pk_ = int(db.I([h + 29])[0]); rr = db.lookup_all(pk_)
    if not rr: stat['no_pattern'] += 1; continue
    S = int(db.lookup_stride([pk_])[0]); r0 = rr[0]
    stat[('pattern_stride', S)] += 1
    # find u/v arrays: offsets where float32 runs match truth x / y in order
    n = len(g['bolts'])
    if n >= 2:
        F = db.F(r0 + np.arange(S - 3))
        for ub in range(13, S - 4 * n, 4):
            u = db.F(r0 + ub + 4 * np.arange(n))
            if np.all(np.isfinite(u)) and np.allclose(np.sort(u), np.sort(T[:, 0]), atol=0.6):
                for vb in range(ub + 4, S - 4 * n, 4):
                    v = db.F(r0 + vb + 4 * np.arange(n))
                    D = np.linalg.norm(np.stack([u, v], 1)[:, None] - T[None, :, :2], axis=2)
                    if (D.min(1) < 0.6).all() and (D.min(0) < 0.6).all():
                        lay_try[(S, ub, vb - ub)] = lay_try.get((S, ub, vb - ub), 0) + 1
    if len(exa) < 3: exa.append((g['guid'][:8], S, np.round(T[:4], 2).tolist(), round(L, 2), sgn))
print(stat)
print('pattern array layouts (stride, u offset, v-u gap): count', sorted(lay_try.items(), key=lambda x: -x[1])[:8])
for e in exa: print(e)
