import sys, json, collections, numpy as np, ifcopenshell
import ifcopenshell.util.element as ue
from cache import *
from guid2 import guid_keys
from db1bolts2 import BoltDecoder
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
bd = BoltDecoder(db, pts, cs, lay); G = bd.decode(M); bys = {g['seq']: g for g in G}
GK, back, top = guid_keys(db)
f = ifcopenshell.open(ifc)
c = collections.Counter()
for e in f.by_type('IfcMechanicalFastener'):
    g = bys.get(GK.get((e.Tag or '')[2:38].upper()))
    if g is None: continue
    ps = {}
    for kk, v in ue.get_psets(e).items():
        if 'Bolt' in kk or 'Fastener' in kk: ps.update(v)
    hd = ps.get('Bolt hole diameter'); sy = ps.get('Slotted hole y'); sx = ps.get('Slotted hole x')
    a = db.lookup_all(g['attr'])[0]; S = int(db.lookup_stride([g['attr']])[0])
    key = []
    if hd and abs(g['d'] + g['tol'] - hd) >= 0.06: key.append(('hole', round(g['d'], 2), round(g['tol'], 3), hd, int(db.I([a + 21])[0])))
    if sy is not None and abs(g['slot_y'] - sy) >= 0.06: key.append(('sy', round(g['slot_y'], 2), sy, round(g['slot_x'], 2), sx, int(db.I([a + 21])[0])))
    for k in key: c[k] += 1
for k, v in c.most_common(20): print(v, k)
