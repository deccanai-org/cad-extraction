import sys, json, collections, numpy as np
from cache import *
from guid2 import guid_keys
from db1bolts2 import BoltDecoder
import ifcbolts
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
bd = BoltDecoder(db, pts, cs, lay); G = bd.decode(M); bys = {g['seq']: g for g in G}
GK, back, top = guid_keys(db)
_, GR = ifcbolts.bolts(ifc, True)
hits = collections.Counter(); n = 0
for tb in GR:
    k = GK.get(tb['guid']); g = bys.get(k)
    if g is None or not tb['bolts']: continue
    T = np.array([[(b['start'] - g['O']) @ g['x'], (b['start'] - g['O']) @ g['y']] for b in tb['bolts']])
    P = np.array(g['uv'])
    if len(P) != len(T): continue
    d = T.mean(0) - P.mean(0)
    D = np.linalg.norm(P[:, None] + d - T[None], axis=2)
    if not ((D.min(1) < 1).all() and np.linalg.norm(d) > 1): continue
    n += 1
    for nm, val in (('dx', d[0]), ('dy', d[1])):
        if abs(val) < 1: continue
        for base, S, tag in ((g['off'], g['stride'], 'grp'), (db.lookup_all(g['attr'])[0], int(db.lookup_stride([g['attr']])[0]), 'attr'), (db.lookup_all(g['poly'])[0], 341, 'pat')):
            F = db.F(base + np.arange(S - 3)); Dd = db.D(base + np.arange(S - 7))
            for kk in np.nonzero(np.isfinite(F) & (np.abs(np.abs(F) - abs(val)) < 0.06))[0]: hits[(nm, tag, 'F', int(kk), 'sign' if F[kk] * val > 0 else 'neg')] += 1
            for kk in np.nonzero(np.isfinite(Dd) & (np.abs(np.abs(Dd) - abs(val)) < 0.06))[0]: hits[(nm, tag, 'D', int(kk), 'sign' if Dd[kk] * val > 0 else 'neg')] += 1
print('translated groups', n)
for k, v in hits.most_common(15): print(v, k)
