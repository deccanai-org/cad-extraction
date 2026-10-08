"""IfcPlate truth with arcs: global outline as a DENSE polyline (IfcPolyline and
IfcCompositeCurve of polylines + trimmed circles), thickness, normal. -> <ifc>.plates2.pkl"""
import ifcopenshell, ifcopenshell.util.placement as up, ifcopenshell.util.unit as uu, numpy as np, sys, pickle, math
def a2(p, sc):
    loc = np.array(list(p.Location.Coordinates)[:2]) * sc
    rd = np.array(list(p.RefDirection.DirectionRatios)[:2]) if getattr(p, 'RefDirection', None) else np.array([1., 0])
    rd = rd / np.linalg.norm(rd); return loc, rd, np.array([-rd[1], rd[0]])
def curve_pts(c, sc, step=math.radians(3)):
    if c.is_a('IfcPolyline'):
        return [np.array(list(p.Coordinates)[:2]) * sc for p in c.Points]
    if c.is_a('IfcCompositeCurve'):
        out = []
        for s in c.Segments:
            q = curve_pts(s.ParentCurve, sc, step)
            if not s.SameSense: q = q[::-1]
            if out and q and np.linalg.norm(out[-1] - q[0]) < 1e-6: q = q[1:]
            out += q
        return out
    if c.is_a('IfcTrimmedCurve'):
        b = c.BasisCurve
        if not b.is_a('IfcCircle'): raise ValueError(b.is_a())
        C, X, Y = a2(b.Position, sc); R = b.Radius * sc
        def par(tr):
            for t in tr:
                if t.is_a('IfcParameterValue'): return float(t.wrappedValue)
            for t in tr:
                if t.is_a('IfcCartesianPoint'):
                    v = np.array(list(t.Coordinates)[:2]) * sc - C; return math.atan2(v @ Y, v @ X)
        t1, t2 = par(c.Trim1), par(c.Trim2)
        if c.SenseAgreement:
            while t2 < t1: t2 += 2 * math.pi
        else:
            while t2 > t1: t2 -= 2 * math.pi
        n = max(2, int(abs(t2 - t1) / step) + 1)
        return [C + R * (math.cos(t) * X + math.sin(t) * Y) for t in np.linspace(t1, t2, n + 1)]
    raise ValueError(c.is_a())
def plates(path):
    f = ifcopenshell.open(path); sc = uu.calculate_unit_scale(f) * 1000; out = []; bad = 0
    rect_beams = '--rect-beams' in sys.argv
    for e in f.by_type('IfcPlate') + (f.by_type('IfcBeam') if rect_beams else []):
        if not e.Representation: continue
        M = np.array(up.get_local_placement(e.ObjectPlacement)); M[:3, 3] *= sc
        for r in e.Representation.Representations:
            for it in r.Items:
                while True:
                    if it.is_a('IfcMappedItem'): it = it.MappingSource.MappedRepresentation.Items[0]
                    elif it.is_a('IfcBooleanResult'): it = it.FirstOperand
                    else: break
                if not it.is_a('IfcExtrudedAreaSolid'): continue
                if it.SweptArea.is_a('IfcRectangleProfileDef') and e.is_a('IfcBeam'):
                    # parametric plate written as a beam: rebuild its plate outline (L x width, thickness = small side)
                    pr = it.SweptArea; X, Y = pr.XDim * sc, pr.YDim * sc
                    P = np.array(up.get_axis2placement(it.Position)); P[:3, 3] *= sc; G = M @ P
                    ex, ey, ez = G[:3, 0], G[:3, 1], G[:3, :3] @ np.array(it.ExtrudedDirection.DirectionRatios)
                    c0 = G[:3, 3].copy()
                    if pr.Position is not None:
                        q = np.array(up.get_axis2placement(pr.Position)); c0 = c0 + G[:3, :3] @ np.array([q[0, 3] * sc, q[1, 3] * sc, 0.0])
                    w, b, n, t = (ex, X, ey, Y) if X >= Y else (ey, Y, ex, X)
                    D = it.Depth * sc; base = c0 - n * t / 2
                    glob = np.array([base - w * b / 2, base + w * b / 2, base + w * b / 2 + ez * D, base - w * b / 2 + ez * D])
                    out.append(dict(guid=e.GlobalId, prof=pr.ProfileName, pts=glob, t=t, n=n, arcs=False, beam=True)); continue
                if not it.SweptArea.is_a('IfcArbitraryClosedProfileDef'): continue
                try: loc = curve_pts(it.SweptArea.OuterCurve, sc)
                except Exception: bad += 1; continue
                P = np.array(up.get_axis2placement(it.Position)); P[:3, 3] *= sc; G = M @ P
                glob = np.array([G[:3, :3] @ np.array([v[0], v[1], 0.0]) + G[:3, 3] for v in loc])
                d = np.array(it.ExtrudedDirection.DirectionRatios)
                out.append(dict(guid=e.GlobalId, prof=it.SweptArea.ProfileName, pts=glob, t=it.Depth * sc, n=G[:3, :3] @ d,
                                arcs=it.SweptArea.OuterCurve.is_a('IfcCompositeCurve')))
    return out, bad
if __name__ == '__main__':
    o, bad = plates(sys.argv[1]); pickle.dump(o, open(sys.argv[1] + '.plates2.pkl', 'wb'))
    print(len(o), 'plates;', sum(p['arcs'] for p in o), 'with arcs; unreadable', bad)
