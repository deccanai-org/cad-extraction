"""shared helpers for 8.x bolt RE"""
import numpy as np, collections
from cache import *
from guidmap import db1_guids
import ifcbolts
SENT = 2147483647
def setup(db1, ifc):
    db, pts, cs, lay, M = get(db1)
    seqs = {m['seq']: m for m in M}
    G, info = db1_guids(db.b)
    B, GR = ifcbolts.bolts(ifc, True)
    pairs = [(g, seqs[G[g['guid']]['key']]) for g in GR if g['guid'] in G and G[g['guid']]['key'] in seqs]
    return db, pts, cs, lay, M, seqs, pairs
def recs341(db, m, PF=29, PS=341):
    k = int(db.I([m['off'] + PF])[0]); recs = db.lookup_all(k, PS)
    byidx = {}
    for r in recs: byidx.setdefault(int(db.I([r + 13])[0]), r)
    return [byidx[i] for i in range(len(byidx)) if i in byidx]
def positions(db, m, PF=29, PS=341):
    out = []
    for r in recs341(db, m, PF, PS):
        u = db.F(r + 21 + 4 * np.arange(10)); v = db.F(r + 61 + 4 * np.arange(10)); w = db.F(r + 101 + 4 * np.arange(10))
        ty = db.I(r + 221 + 4 * np.arange(10)); e = np.nonzero(ty == SENT)[0]; n = int(e[0]) if len(e) else 10
        out += [(float(u[j]), float(v[j]), float(w[j]), int(ty[j])) for j in range(n)]
        if n < 10: break
    return out
def truth_local(g, m):
    z = np.cross(m['x'], m['y'])
    return np.array([[(b['start'] - m['O']) @ m['x'], (b['start'] - m['O']) @ m['y'], (b['start'] - m['O']) @ z] for b in g['bolts']])
def classify(P, T, tol=0.5):
    if P is None or not len(P): return 'no_rec', None
    if len(P) != len(T): return 'count', None
    Pa = np.array([p[:2] for p in P]); D = np.linalg.norm(Pa[:, None, :] - T[None, :, :2], axis=2)
    if (D.min(1) < tol).all() and (D.min(0) < tol).all(): return 'exact', np.zeros(2)
    d = T[:, :2].mean(0) - Pa.mean(0); D2 = np.linalg.norm(Pa[:, None, :] + d - T[None, :, :2], axis=2)
    if (D2.min(1) < tol).all(): return 'translated', d
    return 'other', None
