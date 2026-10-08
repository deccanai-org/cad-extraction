"""(a) sign of the group x vs truth bolt axis; (b) why stride-65 bolt records of not-decoded GUIDs were rejected"""
import sys, os, json, numpy as np, collections
sys.path.insert(0, '/work/agentwork/db1v2-val/code')
from cache import get
from guid2 import guid_keys
from db1bolts2 import BoltDecoder, LAYS
from db1dec import inkeys
import ifcbolts
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
bd = BoltDecoder(db, pts, cs, lay); G = {g['seq']: g for g in bd.decode(M)}
GK, back, _ = guid_keys(db); _, GR = ifcbolts.bolts(ifc, True)
c = collections.Counter()
for tb in GR:
    g = G.get(GK.get(tb['guid']))
    if g is None or not tb['bolts']: continue
    ax = np.mean([b['axis'] for b in tb['bolts']], 0)
    c[(g['lay'], 'sgn', g.get('sgn'), 'axis.z_signed<0', bool(ax @ g['z'] < 0))] += 1
print('sign vs axis:'); [print('  ', v, k) for k, v in sorted(c.items(), key=lambda x: -x[1])]
# (b) rejected stride-65 records
P = bd.P; C = bd.C; why = collections.Counter(); n = 0
for tb in GR:
    k = GK.get(tb['guid'])
    if k is None or k in G: continue
    for o in db.lookup_all(k):
        S = int(db.lookup_stride([k])[0])
        if int(db.I([o + 8 - 8])[0]) and True: pass
        L = LAYS[0]
        a = int(db.I([o + 13])[0]); ao = db.lookup([a])[0]
        if ao < 0: why['attr_not_found'] += 1; continue
        ob = int(db.I([int(ao) + 13])[0])
        if ob != 10: why[('attr_obj', ob)] += 1; continue
        X = db.D(o + 33 + 8 * np.arange(4)); p1 = db._pt(P, db.I([o + 17]))[0]; p2 = db._pt(P, db.I([o + 21]))[0]; cv = int(db.I([o + 29])[0])
        why[('X_ok', bool(np.all(np.isfinite(X)) and np.all(np.abs(X[:3]) < 1e8)), 'p_ok', bool(np.all(np.isfinite(p1)) and np.all(np.isfinite(p2))), 'csys_ok', cv in C['map'])] += 1
        n += 1
        break
    if n > 3000: break
print('rejected reasons:', why.most_common(10))
