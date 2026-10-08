import sys, numpy as np, collections, ifcopenshell
from bolt853 import *
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M, seqs, pairs = setup(db1, ifc)
f = ifcopenshell.open(ifc); tag = {(e.Tag or '')[2:38].upper(): e for e in f.by_type('IfcMechanicalFastener')}
hits = collections.defaultdict(collections.Counter); n = 0; shared = collections.Counter()
for g, m in pairs:
    T = truth_local(g, m)
    if not len(T): continue
    zh = float(T[0, 2])
    e = tag[g['guid']]; it = e.Representation.Representations[0].Items[0]
    hole = (g['pset'].get('Bolt hole diameter') or 0)
    hc = [x for x in it.MappingSource.MappedRepresentation.Items if x.SweptArea.is_a('IfcCircleProfileDef') and abs(2 * x.SweptArea.Radius - hole) < 0.05]
    grip = sum(x.Depth for x in hc) if hc else None
    rr = db.attr_records(lay, m['attr'])
    if not rr or grip is None: continue
    n += 1; a = rr[0]; S = 317
    tv = {'zh': zh, 'grip': grip, 'zc': zh - grip / 2, 'zlow': zh - grip}
    for nm, t in tv.items():
        if abs(t) < 0.3: continue
        for base, tagn, SS in ((a, 'attr', 317), (m['off'], 'mem', 73)):
            F = db.F(base + np.arange(SS - 3)); D = db.D(base + np.arange(SS - 7))
            for k in np.nonzero(np.isfinite(F) & (np.abs(F - t) < 0.06))[0]: hits[nm][(tagn, 'F', int(k))] += 1
            for k in np.nonzero(np.isfinite(D) & (np.abs(D - t) < 0.06))[0]: hits[nm][(tagn, 'D', int(k))] += 1
print('n', n)
for nm, c in hits.items(): print(nm, c.most_common(5))
