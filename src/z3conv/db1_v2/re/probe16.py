import sys, numpy as np, collections, ifcopenshell
from bolt853 import *
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M, seqs, pairs = setup(db1, ifc)
f = ifcopenshell.open(ifc); tag = {(e.Tag or '')[2:38].upper(): e for e in f.by_type('IfcMechanicalFastener')}
c = collections.Counter()
for g, m in pairs:
    rr = db.attr_records(lay, m['attr'])
    if not rr: continue
    flags = int(db.I([rr[0] + 301])[0]); e = tag[g['guid']]
    it = e.Representation.Representations[0].Items[0]
    radii = sorted(set(round(x.SweptArea.Radius * 2, 2) for x in it.MappingSource.MappedRepresentation.Items if x.SweptArea.is_a('IfcCircleProfileDef')))
    kinds = len(it.MappingSource.MappedRepresentation.Items)
    c[(flags, round(g['d'], 2) in radii, kinds)] += 1
for k, v in c.most_common(20): print(v, 'flags', k[0], 'shank_dia_present', k[1], 'n_solids', k[2])
