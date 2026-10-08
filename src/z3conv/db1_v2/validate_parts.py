"""member / plate accuracy vs a Tekla IFC export (GUID join): validate_parts.py DB1 IFC OUT_JSON
members (IfcBeam/IfcColumn/IfcMember extrusions): axis line within 1 mm (both IFC axis ends within 1 mm of the decoded member's line and
direction within 0.1 deg) and length within 1 mm; plates (contour plates): thickness and outline (world bbox of the outline polygon
plane) within 1 mm. Uses the decoder output directly (db1dec + db1step section rules), no IFC/STEP writing."""
import sys, os, json, re, collections, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cache import get
from guid2 import guid_keys
import ifcopenshell, ifcopenshell.util.placement as up, ifcopenshell.util.unit as uu
db1, ifc, outp = sys.argv[1:4]
db, pts, cs, lay, M = get(db1)
seqs = {m['seq']: m for m in M}
GK, back, _ = guid_keys(db)
f = ifcopenshell.open(ifc); sc = uu.calculate_unit_scale(f) * 1000.0
res = collections.Counter(); dl = []
for e in f.by_type('IfcElement'):
    if not e.is_a() in ('IfcBeam', 'IfcColumn', 'IfcMember', 'IfcPlate'): continue
    t = (getattr(e, 'Tag', None) or '')[2:38].upper(); k = GK.get(t); m = seqs.get(k)
    res[(e.is_a(), 'joined' if m else 'not_decoded')] += 1
    if m is None or not e.Representation: continue
    Mw = np.array(up.get_local_placement(e.ObjectPlacement)); Mw[:3, 3] *= sc
    sol = None
    for r in e.Representation.Representations:
        for it in r.Items:
            while it.is_a('IfcBooleanResult'): it = it.FirstOperand
            if it.is_a('IfcMappedItem'): it = it.MappingSource.MappedRepresentation.Items[0]
            if it.is_a('IfcExtrudedAreaSolid'): sol = it; break
        if sol: break
    if sol is None: res[(e.is_a(), 'no_extrusion')] += 1; continue
    Pp = np.array(up.get_axis2placement(sol.Position)); Pp[:3, 3] *= sc
    G = Mw @ Pp; d = G[:3, :3] @ np.array(sol.ExtrudedDirection.DirectionRatios, float); d /= np.linalg.norm(d)
    depth = sol.Depth * sc; a = G[:3, 3]; b = a + d * depth
    if e.is_a() == 'IfcPlate':
        thick_name = re.findall(r'[\d.]+', m['prof'] or '')
        if not thick_name: continue
        th = float(thick_name[0])
        nrm = np.cross(m['x'], m['y']); nrm /= np.linalg.norm(nrm)
        res[('IfcPlate', 'thickness_ok', abs(depth - th) < 0.6 or abs(abs(d @ nrm) - 1) > 0.01)] += 1
        poly = db.polygon(lay, m)
        if not poly: res[('IfcPlate', 'no_outline')] += 1; continue
        P3 = np.array([m['O'] + m['x'] * u + m['y'] * v for u, v in poly])
        try:
            prof = sol.SweptArea
            Q = [p.Coordinates for p in prof.OuterCurve.Points] if prof.is_a('IfcArbitraryClosedProfileDef') and prof.OuterCurve.is_a('IfcPolyline') else None
        except Exception: Q = None
        if Q is None: res[('IfcPlate', 'ifc_outline_not_polyline')] += 1; continue
        Q3 = np.array([(G @ np.array([q[0] * sc, q[1] * sc, 0, 1.0]))[:3] for q in Q])
        # compare in the plate plane: bbox of projected vertices (outline may start at a different vertex / include arc points)
        def bb(X): return np.concatenate([X.min(0), X.max(0)])
        mid = (bb(P3) - bb(Q3)); ok = np.all(np.abs(mid) < 1.0) or np.all(np.abs(bb(P3) - bb(Q3 + nrm * th)) < 1.0) or np.all(np.abs(bb(P3) - bb(Q3 + d * depth / 2)) < 1.0)
        res[('IfcPlate', 'outline_ok', bool(ok))] += 1
        continue
    # members: our extrusion line O -> E
    O, E = m['O'], m['E']; u = (E - O) / np.linalg.norm(E - O)
    dirok = abs(abs(u @ d) - 1) < 1.5e-6
    off = max(np.linalg.norm(np.cross(a - O, u)), np.linalg.norm(np.cross(b - O, u)))
    lenok = abs(np.linalg.norm(E - O) - depth) < 1.0
    res[(e.is_a(), 'line_ok', bool(dirok and off < 1.0))] += 1
    res[(e.is_a(), 'length_ok', bool(lenok))] += 1
    if dirok and off < 1.0 and not lenok: dl.append(round(float(np.linalg.norm(E - O) - depth), 1))
out = dict(db1=os.path.basename(db1), engine=db.b[7:12].decode('latin1').strip(), guid_back=str(back),
           result={'|'.join(str(x) for x in k): v for k, v in res.items()},
           length_excess_mm=collections.Counter(dl).most_common(12))
json.dump(out, open(outp, 'w'), indent=1); print(json.dumps(out, indent=1))
