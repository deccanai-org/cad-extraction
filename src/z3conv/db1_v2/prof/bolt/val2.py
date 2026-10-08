"""IFC bolt assemblies vs DB1 flags + model screwdb catalog (side-aware: positions relative to the shank)."""
import sys, json, collections, numpy as np
sys.path.insert(0, '/Users/dhiren/Downloads/Deccan/z3conv/db1_v2/re'); sys.path.insert(0, '.')
from bolt853 import setup
import screwdb, ifcopenshell, ifcopenshell.util.unit as uu
db1, ifc, sdb = sys.argv[1:4]
db, pts, cs, lay, M, seqs, pairs = setup(db1, ifc)
S = {r['name']: r for r in screwdb.screws(sdb)['rows']}
f = ifcopenshell.open(ifc); sc = uu.calculate_unit_scale(f) * 1000.0
E = {(e.Tag or '')[2:38].upper(): e for e in f.by_type('IfcMechanicalFastener')}
def af(prof):
    p = np.array([q.Coordinates for q in prof.OuterCurve.Points]); w = p.max(0) - p.min(0); return float(min(w)) * sc
side = collections.Counter(); dims = collections.Counter(); ex = []
for g, m in pairs:
    rr = db.attr_records(lay, m['attr'])
    if not rr: continue
    fl = f'{int(db.I([rr[0] + 301])[0]):06d}'
    e = E.get(g['guid'])
    try: items = e.Representation.Representations[0].Items[0].MappingSource.MappedRepresentation.Items
    except Exception: continue
    d, L, hole = g['d'], g['L'], g['pset'].get('Bolt hole diameter') or 0
    it = []
    for x in items:
        y0 = x.Position.Location.Coordinates[1] * sc; dep = x.Depth * sc
        if x.SweptArea.is_a('IfcCircleProfileDef'): it.append(('c', y0, dep, 2 * x.SweptArea.Radius * sc))
        else:
            try: it.append(('p', y0, dep, af(x.SweptArea)))
            except Exception: it.append(('p', y0, dep, None))
    sh = [x for x in it if x[0] == 'c' and abs(x[3] - d) < 0.05 and abs(x[2] - L) < 0.05]
    if fl[0] == '1':
        side[('holes_only', 'shank' if sh else 'no_shank')] += 1; continue
    if not sh: side['no_shank_found'] += 1; continue
    ys, ye = sh[0][1], sh[0][1] + L
    head = [x for x in it if x[0] == 'p' and abs(x[1] + x[2] - ys) < 0.3]
    wash = [x for x in it if x[0] == 'c' and x[3] > 1.3 * d and abs(x[3] - hole) > 0.6]
    hw = [w for w in wash if abs(w[1] - ys) < 0.3]
    nw = [w for w in wash if w not in hw]
    nuts = [x for x in it if x[0] == 'p' and x not in head and x[3] is not None and x[1] >= ys + 0.3]
    pred = (int(fl[1]), int(fl[2]) + int(fl[3]), int(fl[4]) + int(fl[5]))
    got = (len(hw), len(nw), len(nuts))
    side[('flags_match_ifc', pred == got)] += 1
    if pred != got and len(ex) < 8: ex.append((fl, pred, got, [(x[0], round(x[1], 2), round(x[2], 2), x[3] and round(x[3], 2)) for x in it]))
    # catalog dims
    bn, wn, nn = g['pset'].get('Bolt Name'), g['pset'].get('Washer name'), g['pset'].get('Nut name')
    if bn in S and head:
        b = S[bn]['p']; dims[('head k', abs(head[0][2] - b[0]) < 0.05)] += 1
        if head[0][3]: dims[('head s', abs(head[0][3] - b[3]) < 0.1)] += 1
    elif head: dims['head: bolt name not in catalog'] += 1
    if wn in S:
        for w in wash: dims[('washer t,OD', abs(w[2] - S[wn]['p'][0]) < 0.05 and abs(w[3] - S[wn]['p'][3]) < 0.1)] += 1
    if nn in S:
        for n_ in nuts: dims[('nut m', abs(n_[2] - S[nn]['p'][0]) < 0.05)] += 1
print(json.dumps({str(k): v for k, v in side.items()}, indent=0)); print(json.dumps({str(k): v for k, v in dims.items()}, indent=0))
for x in ex: print(x)
