"""head-z failures + not-decoded GUIDs diagnostics. diag33.py DB1 IFC CONV_JSON"""
import sys, os, json, numpy as np, collections
sys.path.insert(0, '/work/agentwork/db1v2-val/code')
from cache import get
from guid2 import guid_keys
from db1bolts2 import BoltDecoder
import ifcbolts, truthmesh, ifcopenshell
db1, ifc, cj = sys.argv[1:4]
st = json.load(open(cj)); dbg = st.get('bolt_debug') or {}
db, pts, cs, lay, M = get(db1)
bd = BoltDecoder(db, pts, cs, lay); G = {g['seq']: g for g in bd.decode(M)}
GK, back, _ = guid_keys(db)
_, GR = ifcbolts.bolts(ifc, True)
f = ifcopenshell.open(ifc); byg = {(e.Tag or '')[2:38].upper(): e for e in f.by_type('IfcMechanicalFastener')}
fails = collections.Counter(); ex = []; nd = collections.Counter(); axis = collections.Counter()
for tb in GR:
    k = GK.get(tb['guid']); g = G.get(k)
    if g is None:
        ss = tuple(sorted(int(s) for s, (K, O) in db.seqidx.items() if k is not None and np.searchsorted(K, k, 'right') > np.searchsorted(K, k, 'left')))
        nd[ss] += 1; continue
    rows = dbg.get(str(k))
    if not rows or (g.get('flagbits') or {}).get('bolt') is False: continue
    if tb['bolts']:
        T = np.array([[(b['start'] - g['O']) @ g['x'], (b['start'] - g['O']) @ g['y'], (b['start'] - g['O']) @ g['z']] for b in tb['bolts']])
        ax = [round(float(b['axis'] @ g['z']), 3) for b in tb['bolts']]
    else:
        try: V = truthmesh.mesh(byg[tb['guid']])
        except Exception: continue
        R = V - g['O']; Q = np.stack([R @ g['x'], R @ g['y'], R @ g['z']], 1); T = []; ax = []
        for r in rows:
            sel = np.linalg.norm(Q[:, :2] - [r[0], r[1]], axis=1) <= g['d'] / 2 + 0.5
            if sel.sum() >= 6:
                zz = Q[sel, 2]; T.append([r[0], r[1], float(zz.max())]); ax.append(0.0)
        if not T: continue
        T = np.array(T)
    for (u, v, zh, grip, how) in rows:
        D = np.linalg.norm(T[:, :2] - [u, v], axis=1); j = int(np.argmin(D))
        if D[j] > 1 or zh is None: continue
        e = zh - T[j, 2]
        key = (g.get('standard'), g.get('flags'), round(float(e), 2), ax[j])
        axis[ax[j] < 0] += 1
        if abs(e) > 1:
            fails[key] += 1
            if len(ex) < 12: ex.append(dict(std=g.get('standard'), flags=g.get('flags'), zc=round(g.get('zc') or 0, 2), grip=grip, how=how, zh=zh, truth=round(float(T[j, 2]), 2), axis=ax[j], L=g['L'], d=g['d']))
print('axis -z share', dict(axis))
print('head-z failures by (standard, flags, error, axis):'); [print('  ', v, k) for k, v in fails.most_common(15)]
for x in ex: print('  ex', x)
print('not decoded GUID keys -> strides', nd.most_common(8))
