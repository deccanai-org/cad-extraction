import sys, collections, numpy as np, re
from cache import *
from guidmap import db1_guids
import ifcbolts
SENT = 2147483647
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
seqs = {m['seq']: m for m in M}
G, info = db1_guids(db.b)
B, GR = ifcbolts.bolts(ifc, True)
pairs = [(g, seqs[G[g['guid']]['key']]) for g in GR if g['guid'] in G and G[g['guid']]['key'] in seqs]
PF = int(sys.argv[3]) if len(sys.argv) > 3 else 29; PS = int(sys.argv[4]) if len(sys.argv) > 4 else 341
def positions(m):
    k = int(db.I([m['off'] + PF])[0]); recs = db.lookup_all(k, PS)
    if not recs: return None
    byidx = {}
    for r in recs: byidx.setdefault(int(db.I([r + 13])[0]), r)
    out = []
    for i in range(len(byidx)):
        r = byidx.get(i)
        if r is None: break
        u = db.F(r + 21 + 4 * np.arange(10)); v = db.F(r + 61 + 4 * np.arange(10)); w = db.F(r + 101 + 4 * np.arange(10))
        ty = db.I(r + 221 + 4 * np.arange(10)); e = np.nonzero(ty == SENT)[0]; n = int(e[0]) if len(e) else 10
        out += [(float(u[j]), float(v[j]), float(w[j]), int(ty[j])) for j in range(n)]
        if n < 10: break
    return out
st = collections.Counter(); offs = collections.Counter(); ex = []
for g, m in pairs:
    z = np.cross(m['x'], m['y'])
    T = np.array([[ (b['start'] - m['O']) @ m['x'], (b['start'] - m['O']) @ m['y'], (b['start'] - m['O']) @ z] for b in g['bolts']])
    P = positions(m)
    if P is None: st['no_rec'] += 1; continue
    if len(P) != len(T): st['count_mismatch'] += 1; ex.append((g['guid'][:8], len(P), len(T), [p[:2] for p in P][:4], T[:4, :2].round(1).tolist())); continue
    Pa = np.array([p[:2] for p in P])
    # greedy match
    D = np.linalg.norm(Pa[:, None, :] - T[None, :, :2], axis=2)
    ok = (D.min(1) < 0.5).all() and (D.min(0) < 0.5).all()
    if ok: st['exact_xy'] += 1
    else:
        # translation?
        d = T[:, :2].mean(0) - Pa.mean(0); D2 = np.linalg.norm(Pa[:, None, :] + d - T[None, :, :2], axis=2)
        if (D2.min(1) < 0.5).all(): st['translated'] += 1; offs[tuple(np.round(d, 1))] += 1
        else: st['other'] += 1; ex.append((g['guid'][:8], 'other', [tuple(np.round(p[:2], 1)) for p in P][:4], T[:4, :2].round(1).tolist(), g['pset'].get('Slotted hole x'), g['pset'].get('Slotted hole y')))
    st['w_nonzero'] += any(abs(p[2]) > 1e-3 for p in P)
    st[('types', tuple(sorted(set(p[3] for p in P))))] += 1
print(len(pairs), st.most_common())
print('offsets', offs.most_common(10))
for e in ex[:15]: print(e)
