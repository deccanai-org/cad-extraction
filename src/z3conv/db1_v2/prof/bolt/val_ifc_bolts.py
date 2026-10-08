"""Validate the model bolt catalog (screwdb.db) and washer-side flags against a Tekla IFC export.
Per IfcMechanicalFastener (one bolt group): mapped-representation extrusions along local +y (shank y 0..L):
head = non-circle extrusion ending at y=0, nut = non-circle extrusion beyond the grip, washers = circle extrusions with
the washer outer radius; side = head side when the washer starts within 1 mm of y=0, else nut side."""
import sys, json, collections, re, numpy as np
import ifcopenshell, ifcopenshell.util.element as ue, ifcopenshell.util.unit as uu
sys.path.insert(0, '.')
import screwdb
ifc, sdb = sys.argv[1:3]
S = {r['name']: r for r in screwdb.screws(sdb)['rows']}
f = ifcopenshell.open(ifc); sc = uu.calculate_unit_scale(f) * 1000.0
res = collections.Counter(); ex = []; side = {}
def af_of(prof):
    pts = np.array([p.Coordinates for p in prof.OuterCurve.Points])
    w = pts.max(0) - pts.min(0); return float(min(w)) * sc
for e in f.by_type('IfcMechanicalFastener'):
    ps = {}
    for k, v in ue.get_psets(e).items():
        if 'Bolt' in k or 'Fastener' in k: ps.update(v)
    tag = (e.Tag or '')[2:38].upper()
    try:
        it = e.Representation.Representations[0].Items[0]
        items = it.MappingSource.MappedRepresentation.Items
    except Exception:
        res['no_rep'] += 1; continue
    L = float(e.NominalLength or 0) * (sc if sc != 1000 else 1)
    parts = []
    for x in items:
        if not x.is_a('IfcExtrudedAreaSolid'): continue
        y0 = x.Position.Location.Coordinates[1] * sc; dep = x.Depth * sc
        if x.SweptArea.is_a('IfcCircleProfileDef'): parts.append(('circ', y0, dep, 2 * x.SweptArea.Radius * sc))
        else:
            try: parts.append(('poly', y0, dep, af_of(x.SweptArea)))
            except Exception: parts.append(('poly', y0, dep, None))
    hole = ps.get('Bolt hole diameter')
    head = [p for p in parts if p[0] == 'poly' and abs(p[1] + p[2]) < 0.5]
    nut = [p for p in parts if p[0] == 'poly' and p[1] > 0.5]
    wash = [p for p in parts if p[0] == 'circ' and hole and abs(p[3] - hole) > 0.6 and abs(p[2] - L) > 0.05 and p[3] > (e.NominalDiameter or 0) * 1.3]
    hs = sum(1 for w in wash if abs(w[1]) < 1.0); ns = len(wash) - hs
    side[tag] = (hs, ns, len(nut))
    bn, wn, nn = ps.get('Bolt Name'), ps.get('Washer name'), ps.get('Nut name')
    b, w, n = S.get(bn), S.get(wn), S.get(nn)
    res['groups'] += 1
    if b and head:
        res['bolt_in_catalog'] += 1
        ok = abs(head[0][2] - b['p'][0]) < 0.05 and (head[0][3] is None or abs(head[0][3] - b['p'][3]) < 0.1)
        res['head_k_s_match'] += ok
        if not ok and len(ex) < 6: ex.append(('head', bn, head[0], b['p']))
    if w and wash:
        res['washer_in_catalog'] += 1
        ok = all(abs(x[2] - w['p'][0]) < 0.05 and abs(x[3] - w['p'][3]) < 0.1 for x in wash)
        res['washer_t_od_match'] += ok
        if not ok and len(ex) < 12: ex.append(('washer', wn, wash, w['p']))
    if n and nut:
        res['nut_in_catalog'] += 1
        ok = all(abs(x[2] - n['p'][0]) < 0.05 and (x[3] is None or abs(x[3] - n['p'][3]) < 0.1) for x in nut)
        res['nut_m_s_match'] += ok
        if not ok and len(ex) < 18: ex.append(('nut', nn, nut, n['p']))
    res[('per_bolt washers head/nut side, nuts', hs, ns, len(nut))] += 1
print(json.dumps({str(k): v for k, v in res.items()}, indent=0))
for x in ex: print(x)
json.dump(side, open(ifc + '.washer_sides.json', 'w'))
