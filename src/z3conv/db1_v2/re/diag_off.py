import sys, json, collections, numpy as np, ifcopenshell
from cache import *
from guid2 import guid_keys
from db1bolts2 import BoltDecoder
import ifcbolts
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
bd = BoltDecoder(db, pts, cs, lay); G = bd.decode(M); bys = {g['seq']: g for g in G}
GK, back, top = guid_keys(db)
_, GR = ifcbolts.bolts(ifc, True)
c = collections.Counter(); ex = collections.defaultdict(list)
for tb in GR:
    k = GK.get(tb['guid']); g = bys.get(k)
    if g is None or not tb['bolts']: continue
    T = np.array([[(b['start'] - g['O']) @ g['x'], (b['start'] - g['O']) @ g['y']] for b in tb['bolts']])
    P = np.array(g['uv'])
    def fits(Q, trans=False):
        if len(Q) != len(T): return False
        d = (T.mean(0) - Q.mean(0)) if trans else np.zeros(2)
        D = np.linalg.norm(Q[:, None] + d - T[None], axis=2)
        return (D.min(1) < 1.0).all() and (D.min(0) < 1.0).all()
    if fits(P): c['exact'] += 1; continue
    if len(P) != len(T): c['count'] += 1; ex['count'].append((tb['guid'][:8], len(P), len(T), g['lay'], g['src'] if 'src' in g else '')); continue
    found = None
    for nm, Q in (('flip_v', P * [1, -1]), ('flip_u', P * [-1, 1]), ('rot180', -P), ('swap', P[:, ::-1]), ('swap_flip', P[:, ::-1] * [1, -1])):
        if fits(Q): found = nm; break
    if not found:
        for nm, Q in (('trans', P), ('flip_v+t', P * [1, -1]), ('flip_u+t', P * [-1, 1]), ('rot180+t', -P)):
            if fits(Q, True): found = nm; break
    c[found or 'other'] += 1
    if len(ex[found or 'other']) < 5:
        ex[found or 'other'].append((tb['guid'][:8], np.round(P[:3], 1).tolist(), np.round(T[:3], 1).tolist(), round(float(np.round((T.mean(0) - P.mean(0)) @ [1, 0], 1)), 1), g.get('slot_x'), g.get('slot_y'), round(g['Lline'], 1)))
print(c)
for k, v in ex.items():
    print(k)
    for x in v: print('   ', x)
