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
    a = db.lookup_all(g['attr'])[0]; S = int(db.lookup_stride([g['attr']])[0]); sh = S - 317
    i21 = int(db.I([a + 21 + sh])[0]); i25 = int(db.I([a + 25 + sh])[0]); i17 = int(db.I([a + 17 + sh])[0])
    F = lambda k: round(float(db.F([a + k])[0]), 3)
    c[(i21, i17, round(ps.get('Bolt hole diameter', 0) - g['d'], 2), round(g['tol'], 2), (ps.get('Slotted hole x') or 0) > 0, (ps.get('Slotted hole y') or 0) > 0, g['slot_x'] > 0, g['slot_y'] > 0, F(S - 52), F(S - 32), F(S - 28), F(S - 20))] += 1
for k, v in c.most_common(30): print(v, k)
