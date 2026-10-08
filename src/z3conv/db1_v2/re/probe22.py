import sys, numpy as np, collections, ifcopenshell
from bolt853 import *
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M, seqs, pairs = setup(db1, ifc)
f = ifcopenshell.open(ifc); tag = {(e.Tag or '')[2:38].upper(): e for e in f.by_type('IfcMechanicalFastener')}
c = collections.Counter(); ex = []
for g, m in pairs:
    T = truth_local(g, m)
    if not len(T): continue
    zh = float(T[0, 2]); e = tag[g['guid']]; it = e.Representation.Representations[0].Items[0]
    hole = (g['pset'].get('Bolt hole diameter') or 0)
    hc = [x for x in it.MappingSource.MappedRepresentation.Items if x.SweptArea.is_a('IfcCircleProfileDef') and abs(2 * x.SweptArea.Radius - hole) < 0.05]
    grip = sum(x.Depth for x in hc) if hc else None
    rr = db.attr_records(lay, m['attr'])
    if not rr or grip is None: continue
    a = rr[0]; F = lambda k: float(db.F([a + k])[0])
    zc = F(293); fl = int(db.I([a + 301])[0])
    for k in (285, 289, 297, 309, 313):
        c[(k, abs(F(k) - grip) < 0.06)] += 0
    best = [k for k in range(9, 314) if abs(F(k) - grip) < 0.06]
    c[('grip_at', tuple(best[:3]))] += 1
    pred = zc + grip / 2
    c[('zh=zc+grip/2', abs(pred - zh) < 0.1)] += 1
    if abs(pred - zh) >= 0.1 and len(ex) < 8: ex.append((round(zh, 2), round(zc, 2), round(grip, 2), fl, [round(F(k), 2) for k in (285, 289, 293, 297, 309, 313)]))
for k, v in c.most_common(20):
    if v: print(v, k)
for x in ex: print(x)
