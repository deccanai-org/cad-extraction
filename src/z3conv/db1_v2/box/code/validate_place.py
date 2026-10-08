"""compare decoded bolt placement (bolt_debug from run_conv with DB1_BOLT_DEBUG=1) with Tekla IFC truth (GUID join)
   validate_place.py DB1 IFC STATS_JSON"""
import sys, os, json, collections, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cache import get
from guid2 import guid_keys
from db1bolts2 import BoltDecoder
import ifcbolts
db1, ifc, stp = sys.argv[1:4]
st = json.load(open(stp)); dbg = st.get('bolt_debug') or {}
db, pts, cs, lay, M = get(db1)
bd = BoltDecoder(db, pts, cs, lay); G = {g['seq']: g for g in bd.decode(M)}
GK, back, _ = guid_keys(db)
_, GR = ifcbolts.bolts(ifc, True)
c = collections.Counter(); err = collections.defaultdict(list)
import ifcopenshell, truthmesh
f = ifcopenshell.open(ifc); byg = {(e.Tag or '')[2:38].upper(): e for e in f.by_type('IfcMechanicalFastener')}
for tb in GR:
    k = GK.get(tb['guid']); g = G.get(k); rows = dbg.get(str(k))
    if g is None or not rows: continue
    fb = g.get('flagbits') or {}
    if fb.get('bolt') is False: continue
    if tb['bolts']:
        T = np.array([[(b['start'] - g['O']) @ g['x'], (b['start'] - g['O']) @ g['y'], (b['start'] - g['O']) @ g['z']] for b in tb['bolts']])
    else:
        try: V = truthmesh.mesh(byg[tb['guid']])
        except Exception: continue
        R = V - g['O']; Q = np.stack([R @ g['x'], R @ g['y'], R @ g['z']], 1); T = []
        for u, v, *_ in rows:
            sel = np.linalg.norm(Q[:, :2] - [u, v], axis=1) <= g['d'] / 2 + 0.5
            if sel.sum() >= 6: T.append([u, v, float(Q[sel, 2].max())])
        if not T: continue
        T = np.array(T)
    for u, v, zh, grip, how in rows:
        D = np.linalg.norm(T[:, :2] - [u, v], axis=1); j = int(np.argmin(D))
        if D[j] > 1.0: c['xy_off'] += 1; continue
        if zh is None: c['unplaced'] += 1; continue
        e = zh - T[j, 2]; err[how].append(e)
        c[(how, abs(e) < 1.0)] += 1
print(dict(c))
for how, v in err.items():
    v = np.abs(np.array(v)); print(how, 'n', len(v), 'median |dz|', round(float(np.median(v)), 3), 'p90', round(float(np.percentile(v, 90)), 3), 'within 1mm', round(float((v < 1).mean()), 3), 'within 5mm', round(float((v < 5).mean()), 3))
