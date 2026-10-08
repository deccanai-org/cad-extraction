#!/usr/bin/env python3
"""Source inventory of an IFC file (what a faithful STEP must contain), with ifcopenshell.
usage: ifc_census.py FILE.ifc OUT.json [--parts OUT.parts.jsonl.gz]

Per IfcProduct that the converter turns into a part (has a Body/Facetation/unnamed shape representation, not an
opening/space/grid/annotation/virtual element):
  gid, class, name, category (member | connection | rebar | other), representation types (stand-in signal:
  'BoundingBox' / IfcBoundingBox items = box stand-ins), expected volume in mm3:
    q   = from the product's own quantity sets (IfcQuantityVolume Net*/Gross*/Volume), unit-scaled
    an  = analytic NET volume, when the body is one IfcExtrudedAreaSolid of a standard profile without boolean cuts:
          profile areas include fillet / edge radii (hollow sections, T, U, L, Z, C, asymmetric I, rounded rectangle),
          polyline / indexed-polyline / composite-polyline outlines and voids; the volume of the product's openings
          (IfcRelVoidsElement, the same cuts the converter applies) is subtracted:
            exact  - prism openings parallel to a box / polygon host axis, contained in or axis-aligned with the host
            bound  - anything else: the removed volume lies in [lo, hi]  ->  an_lo / an_hi (interval check), an = None
    an_gross / op = gross analytic volume and number of openings (transparency); cv = census version of the record
          (3: net analytic volumes through openings + exact profile areas; grade_join trusts `an` for cv >= 2)
Summary: counts by class and category, schema, units, georeferencing hints, external references."""
import sys, os, json, math, gzip, time, argparse, collections
import ifcopenshell
import ifcopenshell.util.unit
try:
    import numpy as np
    import ifcopenshell.util.placement as uplace
except Exception:                                       # placement maths unavailable: openings -> interval bounds only
    np = None; uplace = None

ap = argparse.ArgumentParser(); ap.add_argument('ifc'); ap.add_argument('out'); ap.add_argument('--parts')
a = ap.parse_args()
T0 = time.time()
CV = 3          # census version per part record (2: HSS corner radii / T root fillets, openings -> no analytic value;
                # 3: + openings subtracted (net / interval), exact areas for every standard profile, voids, derived profiles)
SKIP = {'IfcOpeningElement', 'IfcOpeningStandardCase', 'IfcSpace', 'IfcGrid', 'IfcAnnotation', 'IfcVirtualElement'}
MEMBER = ('IfcBeam', 'IfcColumn', 'IfcMember', 'IfcPile')
CONNECTION = ('IfcPlate', 'IfcMechanicalFastener', 'IfcFastener', 'IfcDiscreteAccessory')
REBAR = ('IfcReinforcingElement',)
SPATIAL = ('IfcSite', 'IfcBuilding', 'IfcBuildingStorey', 'IfcSpatialStructureElement', 'IfcSpatialElement')
BUILDING = ('IfcWall', 'IfcSlab', 'IfcRoof', 'IfcDoor', 'IfcWindow', 'IfcStair', 'IfcRamp', 'IfcCovering', 'IfcCurtainWall',
            'IfcFooting', 'IfcRailing', 'IfcStairFlight', 'IfcRampFlight')
MEP = ('IfcFlowSegment', 'IfcFlowFitting', 'IfcFlowTerminal', 'IfcFlowController', 'IfcDistributionElement',
       'IfcEnergyConversionDevice', 'IfcFlowMovingDevice', 'IfcFlowStorageDevice', 'IfcFlowTreatmentDevice')

f = ifcopenshell.open(a.ifc)
out = {'schema': f.schema, 'parse_sec': round(time.time() - T0, 1), 'census_version': CV}


def scale(kind):
    try:
        return float(ifcopenshell.util.unit.calculate_unit_scale(f, kind))
    except Exception:
        return None


L_SI = scale('LENGTHUNIT') or 1.0                       # metres per file length unit
V_SI = scale('VOLUMEUNIT')                              # m3 per file volume unit (None: not declared -> SI m3)
A_SI = scale('PLANEANGLEUNIT') or 1.0                   # radians per file angle unit (flange slopes)
out['length_unit_m'] = L_SI; out['volume_unit_m3'] = V_SI
MM = L_SI * 1000.0                                      # mm per file length unit


def cat_of(e):
    for c in MEMBER:
        if e.is_a(c): return 'member'
    for c in CONNECTION:
        if e.is_a(c): return 'connection'
    for c in REBAR:
        if e.is_a(c): return 'rebar'
    for c in SPATIAL:
        if e.is_a(c): return 'spatial'
    for c in BUILDING:
        if e.is_a(c): return 'building'
    for c in MEP:
        if e.is_a(c): return 'mep'
    if e.is_a('IfcBuildingElementProxy'): return 'proxy'
    return 'other'


def body_reps(p):
    rep = getattr(p, 'Representation', None)
    if rep is None:
        return []
    return [r for r in rep.Representations if r.RepresentationIdentifier in (None, 'Body', 'Facetation')]


# ------------------------------------------------------------------ profile areas (file length units^2)
Q = 1.0 - math.pi / 4.0         # area between a 90-degree corner and its fillet arc, per radius^2


def corner(r, beta):
    """area between a corner of interior angle beta (radians) and its inscribed fillet arc of radius r"""
    return r * r * (1.0 / math.tan(beta / 2) - (math.pi - beta) / 2) if r else 0.0


def _g(pr, *names):
    """first attribute of `names` the entity has (schema differences IFC2X3 / IFC4), None-safe"""
    for n in names:
        try:
            v = getattr(pr, n)
        except AttributeError:
            continue
        if v is not None:
            return v
    return None


def _r0(pr, *names):
    return float(_g(pr, *names) or 0.0)


def curve_points(c):
    k = ('cp', c.id())
    if k not in _CP:
        _CP[k] = _curve_points(c)
    return _CP[k]


_CP = {}


def _curve_points(c):
    """2D vertex list of a straight-segment closed curve (IfcPolyline, IfcIndexedPolyCurve without arcs,
    IfcCompositeCurve of polylines / line-trimmed segments); None if the curve has arcs or is unsupported"""
    t = c.is_a()
    if t == 'IfcPolyline':
        return [tuple(float(x) for x in q.Coordinates[:2]) for q in c.Points]
    if t == 'IfcIndexedPolyCurve':
        segs = getattr(c, 'Segments', None)
        if segs and any(s.is_a('IfcArcIndex') for s in segs):
            return None
        cl = c.Points.CoordList
        if segs:
            idx = [i for s in segs for i in s.wrappedValue]
            return [tuple(float(x) for x in cl[i - 1][:2]) for i in idx]
        return [tuple(float(x) for x in p[:2]) for p in cl]
    if t == 'IfcCompositeCurve':
        pts = []
        for s in c.Segments:
            pc = s.ParentCurve
            if not pc.is_a('IfcPolyline'):
                return None
            q = [tuple(float(x) for x in v.Coordinates[:2]) for v in pc.Points]
            if getattr(s, 'SameSense', True) is False:
                q = q[::-1]
            pts += q
        return pts
    return None


def poly_area(P):
    n = len(P)
    if n < 3:
        return None
    return abs(sum(P[i][0] * P[(i + 1) % n][1] - P[(i + 1) % n][0] * P[i][1] for i in range(n))) / 2


def prof_area(pr):
    """area in file length units^2 for standard / arbitrary profiles, fillet and edge radii included; None if unknown.
    Sloped U flanges (AISC C / MC channels from SDS/2): thickness measured at FlangeWidth/2 (IFC), taper thicker at the
    web, fillet corners at 90 deg +- slope -- matches the ifcopenshell kernel exactly on 65 real SDS/2 channels.
    Validated against the kernel's exact B-rep (evidence/profile_area_*): every type returned here. No expectation
    (None) where the convention could not be verified: sloped IFC4 I / T / L legs, Z sections (the kernel measures
    FlangeWidth from the web centre line), C sections without lips (the 0.9.0 kernel crashes on them)."""
    t = pr.is_a()
    g = lambda *n: _g(pr, *n)
    r = lambda *n: _r0(pr, *n)
    try:
        if t == 'IfcRectangleProfileDef':
            return g('XDim') * g('YDim')
        if t == 'IfcRoundedRectangleProfileDef':
            return g('XDim') * g('YDim') - 4 * Q * r('RoundingRadius') ** 2
        if t == 'IfcRectangleHollowProfileDef':
            x, y, w = g('XDim'), g('YDim'), g('WallThickness')
            ro, ri = r('OuterFilletRadius'), r('InnerFilletRadius')
            return x * y - (x - 2 * w) * (y - 2 * w) - 4 * Q * (ro * ro - ri * ri)
        if t == 'IfcCircleProfileDef':
            return math.pi * g('Radius') ** 2
        if t == 'IfcCircleHollowProfileDef':
            rr, w = g('Radius'), g('WallThickness')
            return math.pi * (rr * rr - (rr - w) ** 2)
        if t == 'IfcEllipseProfileDef':
            return math.pi * g('SemiAxis1') * g('SemiAxis2')
        if t == 'IfcAsymmetricIShapeProfileDef':
            if r('BottomFlangeSlope') or r('TopFlangeSlope'):
                return None
            h, tw = g('OverallDepth'), g('WebThickness')
            b1, t1 = g('BottomFlangeWidth', 'OverallWidth'), g('BottomFlangeThickness', 'FlangeThickness')
            r1 = r('BottomFlangeFilletRadius', 'FilletRadius')
            b2 = g('TopFlangeWidth') or b1; t2 = g('TopFlangeThickness') or t1
            r2 = float(g('TopFlangeFilletRadius') if g('TopFlangeFilletRadius') is not None else r1)
            e1, e2 = r('BottomFlangeEdgeRadius'), r('TopFlangeEdgeRadius')
            return b1 * t1 + b2 * t2 + (h - t1 - t2) * tw + 2 * Q * (r1 * r1 + r2 * r2) - 2 * Q * (e1 * e1 + e2 * e2)
        if t == 'IfcIShapeProfileDef':
            if r('FlangeSlope'):
                return None
            b, h, tw, tf = g('OverallWidth'), g('OverallDepth'), g('WebThickness'), g('FlangeThickness')
            fr, fe = r('FilletRadius'), r('FlangeEdgeRadius')
            return 2 * b * tf + (h - 2 * tf) * tw + 4 * Q * fr * fr - 4 * Q * fe * fe
        if t == 'IfcLShapeProfileDef':
            if r('LegSlope'):
                return None
            h, b, th = g('Depth'), (g('Width') or g('Depth')), g('Thickness')
            fr, er = r('FilletRadius'), r('EdgeRadius')
            return th * (h + b - th) + Q * fr * fr - 2 * Q * er * er
        if t == 'IfcUShapeProfileDef':
            h, b, tw, tf = g('Depth'), g('FlangeWidth'), g('WebThickness'), g('FlangeThickness')
            fr, er = r('FilletRadius'), r('EdgeRadius')
            sl = r('FlangeSlope') * A_SI
            return (2 * b * tf + (h - 2 * tf) * tw - (b - tw) * tw * math.tan(sl)
                    + 2 * corner(fr, math.pi / 2 + sl) - 2 * corner(er, math.pi / 2 - sl))
        if t == 'IfcTShapeProfileDef':
            if r('FlangeSlope') or r('WebSlope'):
                return None
            h, b, tw, tf = g('Depth'), g('FlangeWidth'), g('WebThickness'), g('FlangeThickness')
            fr, fe, we = r('FilletRadius'), r('FlangeEdgeRadius'), r('WebEdgeRadius')
            return b * tf + (h - tf) * tw + 2 * Q * fr * fr - 2 * Q * fe * fe - 2 * Q * we * we
        if t == 'IfcCShapeProfileDef':
            h, w, th, gi = g('Depth'), g('Width'), g('WallThickness'), r('Girth')
            ri = r('InternalFilletRadius')
            if gi <= 0:
                return None                                            # no lips: unverified (kernel crash)
            L, nb = h + 2 * w + 2 * gi - 4 * th, 4                     # centre line with lips, 4 bends
            return th * (L - nb * (2 - math.pi / 2) * (ri + th / 2))
        if t == 'IfcZShapeProfileDef':
            return None                                                # FlangeWidth convention differs from the kernel
        if t == 'IfcArbitraryProfileDefWithVoids':
            P = curve_points(pr.OuterCurve)
            A = poly_area(P) if P else None
            if A is None:
                return None
            for ic in pr.InnerCurves:
                Pi = curve_points(ic)
                Ai = poly_area(Pi) if Pi else None
                if Ai is None:
                    return None
                A -= Ai
            return A
        if t == 'IfcArbitraryClosedProfileDef':
            P = curve_points(pr.OuterCurve)
            return poly_area(P) if P else None
        if t == 'IfcDerivedProfileDef':
            A = prof_area(pr.ParentProfile)
            op = pr.Operator
            s1 = float(getattr(op, 'Scale', None) or 1.0); s2 = float(getattr(op, 'Scale2', None) or s1)
            return A * abs(s1 * s2) if A else None
    except Exception:
        return None
    return None


def prof_bbox(pr):
    """profile-local 2D bounding box [x0, y0, x1, y1] (parameterized profiles: centred on Position, IFC convention;
    arbitrary profiles: their outline); None if unknown"""
    t = pr.is_a()
    g = lambda *n: _g(pr, *n)
    try:
        if t in ('IfcArbitraryClosedProfileDef', 'IfcArbitraryProfileDefWithVoids'):
            P = curve_points(pr.OuterCurve)
            if not P:
                return None
            xs = [p[0] for p in P]; ys = [p[1] for p in P]
            return [min(xs), min(ys), max(xs), max(ys)]
        if t in ('IfcCircleProfileDef', 'IfcCircleHollowProfileDef'):
            w = h = 2 * g('Radius')
        elif t == 'IfcEllipseProfileDef':
            w, h = 2 * g('SemiAxis1'), 2 * g('SemiAxis2')
        elif t in ('IfcRectangleProfileDef', 'IfcRoundedRectangleProfileDef', 'IfcRectangleHollowProfileDef'):
            w, h = g('XDim'), g('YDim')
        elif t == 'IfcAsymmetricIShapeProfileDef':
            w, h = max(g('BottomFlangeWidth', 'OverallWidth'), g('TopFlangeWidth') or 0), g('OverallDepth')
        elif t == 'IfcIShapeProfileDef':
            w, h = g('OverallWidth'), g('OverallDepth')
        elif t == 'IfcLShapeProfileDef':
            w, h = (g('Width') or g('Depth')), g('Depth')
        elif t in ('IfcUShapeProfileDef', 'IfcTShapeProfileDef'):
            w, h = g('FlangeWidth'), g('Depth')
        elif t == 'IfcCShapeProfileDef':
            w, h = g('Width'), g('Depth')
        elif t == 'IfcZShapeProfileDef':
            w, h = 2 * g('FlangeWidth') - g('WebThickness'), g('Depth')
        else:
            return None
        return [-w / 2, -h / 2, w / 2, h / 2]
    except Exception:
        return None


# ------------------------------------------------------------------ placement maths (numpy)
def a2p2(pos):
    """IfcAxis2Placement2D -> 4x4 (acting in the XY plane); None -> identity"""
    m = np.eye(4)
    if pos is None:
        return m
    loc = pos.Location.Coordinates
    x = pos.RefDirection.DirectionRatios if getattr(pos, 'RefDirection', None) else (1.0, 0.0)
    n = math.hypot(x[0], x[1]) or 1.0
    cx, cy = x[0] / n, x[1] / n
    m[0, 0], m[0, 1], m[1, 0], m[1, 1] = cx, -cy, cy, cx
    m[0, 3], m[1, 3] = float(loc[0]), float(loc[1])
    return m


_MEMO = {}


def _memo(kind, ent, fn):
    k = (kind, ent.id())
    m = _MEMO.get(k)
    if m is None:
        m = _MEMO[k] = fn(ent)
    return m


def a2p3(pos):
    if pos is None:
        return np.eye(4)
    return _memo('a2p', pos, lambda e: np.array(uplace.get_axis2placement(e), dtype=float))


def local_placement(pl):
    return _memo('lp', pl, lambda e: np.array(uplace.get_local_placement(e), dtype=float))


def mapped_tf(it):
    def f_(e):
        mm = uplace.get_mappeditem_transformation(e)
        return None if mm is None else np.array(mm, dtype=float)
    return _memo('map', it, f_)


def prof_frame(pr):
    """parameterized profiles carry a 2D Position; arbitrary / derived profiles are given in solid coordinates"""
    if pr.is_a('IfcParameterizedProfileDef'):
        return a2p2(getattr(pr, 'Position', None))
    return np.eye(4)


def body_solids(items, m=None, depth=0):
    """flatten Body items (through IfcMappedItem) -> [(4x4 object->item matrix, item)]"""
    out = []
    m = np.eye(4) if m is None else m
    for it in items:
        if it.is_a('IfcMappedItem'):
            if depth > 4:
                return None
            mm = mapped_tf(it)
            if mm is None:                                  # 2D operator: unsupported
                return None
            sub = body_solids(it.MappingSource.MappedRepresentation.Items, m @ mm, depth + 1)
            if sub is None:
                return None
            out += sub
        else:
            out.append((m, it))
    return out


def opening_bounds(p, items):
    """removed volume of the product's openings in file units^3 -> (lo, hi, n_openings, exact)
    host = the product's single IfcExtrudedAreaSolid (via <= 1 mapped item). Each opening item that is an
    IfcExtrudedAreaSolid is a prism; in the host frame F (solid Position x profile Position) it must run along one
    axis of F. Box host (rectangle profile): exact when the prism's outline is inside the host cross-section or an
    axis-aligned rectangle (box-box intersection); polygon host: exact for openings along the extrusion axis whose
    outline lies inside the polygon. Everything else contributes [0, min(A, A_bbox-overlap) x overlap] (a true upper
    bound). Overlapping exact pieces (e.g. a slot written as rectangle + 2 circles) -> [max piece, sum]."""
    ops = [rel.RelatedOpeningElement for rel in (getattr(p, 'HasOpenings', None) or [])]
    if not ops:
        return 0.0, 0.0, 0, True
    if np is None or uplace is None or p.ObjectPlacement is None:
        return None
    hs = body_solids(items)
    if not hs or len(hs) != 1 or not hs[0][1].is_a('IfcExtrudedAreaSolid'):
        return None
    hm, h = hs[0]
    hp = h.SweptArea
    dr = h.ExtrudedDirection.DirectionRatios
    nd = math.sqrt(sum(x * x for x in dr))
    if abs(abs(dr[2]) / nd - 1) > 1e-9:
        return None                                         # oblique host prism: no exact frame
    M_obj = local_placement(p.ObjectPlacement)
    F = M_obj @ hm @ a2p3(h.Position) @ prof_frame(hp)
    Finv = np.linalg.inv(F)
    detF = abs(np.linalg.det(F[:3, :3]))
    D = float(h.Depth) * (1 if dr[2] > 0 else -1)
    zr = (min(0.0, D), max(0.0, D))
    box = hp.is_a() == 'IfcRectangleProfileDef'
    poly = None
    if hp.is_a('IfcArbitraryClosedProfileDef') and not hp.is_a('IfcArbitraryProfileDefWithVoids'):
        poly = curve_points(hp.OuterCurve)
    hb = prof_bbox(hp)
    if hb is None:
        return None
    hlo = [hb[0], hb[1], zr[0]]; hhi = [hb[2], hb[3], zr[1]]
    eps = 1e-7 * max(hhi[0] - hlo[0], hhi[1] - hlo[1], hhi[2] - hlo[2], 1e-9)
    exact_pieces = []; bound = 0.0; exact = True
    seen = set()
    for o in ops:
        oitems = [it for r in body_reps(o) for it in r.Items]
        if not oitems:
            continue                                        # opening without a body cuts nothing
        if o.ObjectPlacement is None:
            return None
        osol = body_solids(oitems)
        if osol is None:
            return None
        Mo = local_placement(o.ObjectPlacement)
        for om, s in osol:
            if not s.is_a('IfcExtrudedAreaSolid'):
                return None                                 # boolean / brep opening body: no bound without a kernel
            op_ = s.SweptArea
            odr = s.ExtrudedDirection.DirectionRatios
            ond = math.sqrt(sum(x * x for x in odr))
            A0 = prof_area(op_); ob = prof_bbox(op_)
            if not A0 or ob is None:
                return None
            T = Finv @ Mo @ om @ a2p3(s.Position) @ prof_frame(op_)
            key = tuple(np.round(T, 6).ravel()) + (op_.id(), round(float(s.Depth), 9))
            if key in seen:
                continue                                    # the same cut twice (duplicated opening)
            seen.add(key)
            e = T[:3, :3] @ (np.array(odr, dtype=float) / ond * float(s.Depth))
            el = float(np.linalg.norm(e))
            if el <= 0:
                continue
            k = int(np.argmax(np.abs(e)))
            if abs(e[k]) < el * (1 - 1e-6) or abs(abs(odr[2]) / ond - 1) > 1e-9:
                return None                                 # opening not along a host axis / oblique opening prism
            i, j = [x for x in (0, 1, 2) if x != k]
            # outline of the opening profile in F; the profile plane is perpendicular to e
            if op_.is_a('IfcArbitraryClosedProfileDef') and not op_.is_a('IfcArbitraryProfileDefWithVoids'):
                P2 = curve_points(op_.OuterCurve)
                shape = 'poly'
            elif op_.is_a() == 'IfcRectangleProfileDef':
                P2 = [(ob[0], ob[1]), (ob[2], ob[1]), (ob[2], ob[3]), (ob[0], ob[3])]
                shape = 'rect'
            else:
                P2 = [(ob[0], ob[1]), (ob[2], ob[1]), (ob[2], ob[3]), (ob[0], ob[3])]
                shape = 'other'
            Pf = [T @ np.array([x, y, 0.0, 1.0]) for x, y in P2]
            ck = Pf[0][k]
            q = [(float(v[i]), float(v[j])) for v in Pf]
            A = poly_area(q) if shape in ('poly', 'rect') else A0 * abs(np.linalg.det(T[np.ix_([i, j], [0, 1])]))
            if not A:
                continue
            k0, k1 = sorted((ck, ck + e[k]))
            ov_k = max(0.0, min(hhi[k], k1) - max(hlo[k], k0))
            qi = [v[0] for v in q]; qj = [v[1] for v in q]
            bi0, bi1, bj0, bj1 = min(qi), max(qi), min(qj), max(qj)
            ov_i = max(0.0, min(hhi[i], bi1) - max(hlo[i], bi0)); ov_j = max(0.0, min(hhi[j], bj1) - max(hlo[j], bj0))
            if ov_k <= eps or ov_i <= eps or ov_j <= eps:
                continue                                    # misses the host (bbox test is exact for "no overlap")
            inside = bi0 >= hlo[i] - eps and bi1 <= hhi[i] + eps and bj0 >= hlo[j] - eps and bj1 <= hhi[j] + eps
            vol = None
            if box:
                if inside:
                    vol = A * ov_k
                elif shape == 'rect' and len({round(x, 9) for x in qi}) == 2 and len({round(y, 9) for y in qj}) == 2:
                    vol = ov_i * ov_j * ov_k                # axis-aligned box x box
            elif poly is not None and k == 2 and inside:
                if all(_inside(v, poly) for v in q) and not any(bi0 + eps < x < bi1 - eps and bj0 + eps < y < bj1 - eps for x, y in poly):
                    vol = A * ov_k
            if vol is None:
                exact = False
                bound += min(A, ov_i * ov_j) * ov_k
            else:
                exact_pieces.append((vol, (max(hlo[i], bi0), max(hlo[j], bj0), max(hlo[k], k0), min(hhi[i], bi1), min(hhi[j], bj1), min(hhi[k], k1), i, j, k)))
    # overlapping exact pieces cannot simply be summed
    overl = False
    if len(exact_pieces) > 1:
        boxes = []
        for _, b in exact_pieces:
            lo3 = [0.0] * 3; hi3 = [0.0] * 3
            lo3[b[6]], lo3[b[7]], lo3[b[8]] = b[0], b[1], b[2]; hi3[b[6]], hi3[b[7]], hi3[b[8]] = b[3], b[4], b[5]
            boxes.append((lo3, hi3))
        if len(boxes) > 600:
            overl = True
        else:
            for x in range(len(boxes)):
                for y in range(x + 1, len(boxes)):
                    if all(min(boxes[x][1][c], boxes[y][1][c]) - max(boxes[x][0][c], boxes[y][0][c]) > eps for c in range(3)):
                        overl = True; break
                if overl:
                    break
    s_ex = sum(v for v, _ in exact_pieces)
    lo = (max(v for v, _ in exact_pieces) if exact_pieces else 0.0) if overl else s_ex
    hi = s_ex + bound
    return lo * detF, hi * detF, len(ops), exact and not overl


def _inside(pt, poly):
    x, y = pt; c = False; n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def analytic_volume(items):
    """one IfcExtrudedAreaSolid (also through one IfcMappedItem) of a known profile, no booleans -> (mm3, profile type)"""
    if len(items) != 1:
        return None
    it = items[0]
    sc = 1.0
    if it.is_a('IfcMappedItem'):
        src = it.MappingSource.MappedRepresentation.Items
        tr = it.MappingTarget
        try:
            sc = float(getattr(tr, 'Scale', None) or 1.0)
            if any(getattr(tr, n, None) not in (None, 1.0) for n in ('Scale2', 'Scale3')):
                return None
        except Exception:
            return None
        if len(src) != 1:
            return None
        it = src[0]
    if not it.is_a('IfcExtrudedAreaSolid'):
        return None
    ar = prof_area(it.SweptArea)
    if ar is None or ar <= 0:
        return None
    d = it.Depth
    # oblique extrusion: volume = area x depth x cos(angle between direction and profile normal)
    try:
        dr = it.ExtrudedDirection.DirectionRatios
        n = math.sqrt(sum(x * x for x in dr)); cz = abs(dr[2]) / n if n else 1.0
    except Exception:
        cz = 1.0
    return ar * d * cz * (sc ** 3) * MM ** 3, it.SweptArea.is_a()


def quantity_volume(p):
    best = {}
    try:
        for rel in getattr(p, 'IsDefinedBy', None) or []:
            if not rel.is_a('IfcRelDefinesByProperties'):
                continue
            pd_ = rel.RelatingPropertyDefinition
            if not pd_.is_a('IfcElementQuantity'):
                continue
            for q in pd_.Quantities:
                if q.is_a('IfcQuantityVolume') and q.VolumeValue:
                    nm = (q.Name or '').lower().replace(' ', '')
                    k = 'net' if 'net' in nm else ('gross' if 'gross' in nm else 'vol')
                    best.setdefault(k, float(q.VolumeValue))
                elif q.is_a('IfcQuantityWeight') and q.WeightValue:
                    nm = (q.Name or '').lower().replace(' ', '')
                    best.setdefault('weight_net' if 'net' in nm else 'weight', float(q.WeightValue))
    except Exception:
        return None
    vs = V_SI if V_SI else 1.0
    for k in ('net', 'vol', 'gross'):
        if k in best:
            return {'kind': k, 'mm3': best[k] * vs * 1e9}
    for k in ('weight_net', 'weight'):
        if k in best:
            return {'kind': k, 'mm3': best[k] / 7850.0 * 1e9}
    return None


by_cls = collections.Counter(); by_cat = collections.Counter(); reptypes = collections.Counter()
standins = collections.Counter(); no_body = collections.Counter(); skipped = collections.Counter()
parts = []; n_an = n_q = 0
an_open = collections.Counter()
products = f.by_type('IfcProduct')
for p in products:
    c = p.is_a()
    if c in SKIP:
        skipped[c] += 1; continue
    reps = body_reps(p)
    items = [it for r in reps for it in r.Items]
    if not items:
        no_body[c] += 1; continue
    cat = cat_of(p)
    by_cls[c] += 1; by_cat[cat] += 1
    rt = sorted({r.RepresentationType or '' for r in reps})
    for t in rt:
        reptypes[t] += 1
    box = any(t == 'BoundingBox' for t in rt) or any(it.is_a('IfcBoundingBox') for it in items)
    if box:
        standins[c] += 1
    rec = {'gid': getattr(p, 'GlobalId', None), 'cls': c, 'name': getattr(p, 'Name', None), 'cat': cat, 'rt': rt, 'cv': CV}
    n_op = sum(1 for r in (getattr(p, 'HasOpenings', None) or []) if r.is_a('IfcRelVoidsElement'))
    if n_op:
        rec['op'] = n_op                                  # openings (bolt holes, copes) are cut from the body
    if box:
        rec['standin'] = 'bounding_box'
    av = analytic_volume(items)
    if av:
        rec['pt'] = av[1][3:-10] if av[1].endswith('ProfileDef') else av[1]
        try:
            ob = opening_bounds(p, items)
        except Exception:
            ob = None
        if ob is None:
            an_open['unbounded'] += 1                       # openings we cannot bound: no analytic expectation
        elif ob[2] == 0:
            rec['an'] = round(av[0], 1); n_an += 1
        else:
            lo, hi, nop, ex = ob
            k3 = MM ** 3
            rec['an_gross'] = round(av[0], 1)
            if ex:
                rec['an'] = round(av[0] - lo * k3, 1); n_an += 1; an_open['exact'] += 1
            else:
                rec['an_lo'] = round(max(0.0, av[0] - hi * k3), 1); rec['an_hi'] = round(av[0] - lo * k3, 1)
                n_an += 1; an_open['interval'] += 1
    qv = quantity_volume(p)
    if qv and n_op and qv['kind'] in ('gross', 'weight'):
        qv = None                                         # gross quantities exclude the openings too
    if qv:
        rec['q'] = round(qv['mm3'], 1); rec['qk'] = qv['kind']; n_q += 1
    parts.append(rec)
ext = {}
for t in ('IfcDocumentReference', 'IfcLibraryReference', 'IfcExternallyDefinedHatchStyle', 'IfcExternallyDefinedSurfaceStyle'):
    try:
        n = len(f.by_type(t))
        if n:
            ext[t] = n
    except Exception:
        pass
try:
    apps = sorted({(x.ApplicationFullName or '') + ' ' + (x.Version or '') for x in f.by_type('IfcApplication')})[:5]
except Exception:
    apps = []
out.update({'products_total': len(products), 'expected_parts': len(parts), 'by_category': dict(by_cat),
            'by_class': dict(by_cls.most_common()), 'rep_types': dict(reptypes), 'standins_bounding_box': dict(standins),
            'products_without_body': dict(no_body), 'skipped_nonphysical': dict(skipped), 'with_analytic_volume': n_an,
            'analytic_with_openings': dict(an_open), 'with_quantity_volume': n_q, 'external_refs': ext,
            'applications': apps, 'sec': round(time.time() - T0, 1)})
if a.parts:
    with gzip.open(a.parts, 'wt') as g:
        for r in parts:
            g.write(json.dumps(r) + '\n')
json.dump(out, open(a.out, 'w'))
print(json.dumps(out))
