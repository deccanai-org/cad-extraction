import sys, json, collections
sys.path.insert(0, '/Users/dhiren/Downloads/Deccan/z3conv/db1_v2/re')
from bolt853 import setup
import ifcopenshell, ifcopenshell.util.unit as uu
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M, seqs, pairs = setup(db1, ifc)
f = ifcopenshell.open(ifc); sc = uu.calculate_unit_scale(f) * 1000.0
E = {(e.Tag or '')[2:38].upper(): e for e in f.by_type('IfcMechanicalFastener')}
side = json.load(open(ifc + '.washer_sides.json'))
want = {('011110', (1, 0, 1)): 3, ('000110', (1, 0, 1)): 3, ('010110', (0, 2, 1)): 2, ('010010', (0, 1, 1)): 2, ('000110', (0, 1, 1)): 1, ('000110', (0, 1, 2)): 2}
seen = collections.Counter()
for g, m in pairs:
    rr = db.attr_records(lay, m['attr'])
    if not rr: continue
    fl = f'{int(db.I([rr[0] + 301])[0]):06d}'; s = tuple(side.get(g['guid'], ()))
    k = (fl, s)
    if k not in want or seen[k] >= want[k]: continue
    seen[k] += 1
    e = E[g['guid']]; it = e.Representation.Representations[0].Items[0]
    items = sorted([(round(x.Position.Location.Coordinates[1] * sc, 2), round(x.Depth * sc, 2), x.SweptArea.is_a()[3:7], round(2 * x.SweptArea.Radius * sc, 2) if x.SweptArea.is_a('IfcCircleProfileDef') else None) for x in it.MappingSource.MappedRepresentation.Items])
    print(k, 'L', round(g['L'], 2), 'd', round(g['d'], 2), 'hole', g['pset'].get('Bolt hole diameter'), 'W', g['pset'].get('Washer count'), 'N', g['pset'].get('Nut count'), 'nb', len(g['bolts']))
    for x in items: print('      y0 %8.2f  depth %7.2f  %s  dia %s' % x)
