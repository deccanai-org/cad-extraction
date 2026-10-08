#!/usr/bin/env python3
"""Source inventory of an IFC file (what a faithful STEP must contain), with ifcopenshell.
usage: ifc_census.py FILE.ifc OUT.json [--parts OUT.parts.jsonl.gz]

Per IfcProduct that the converter turns into a part (has a Body/Facetation/unnamed shape representation, not an
opening/space/grid/annotation/virtual element):
  gid, class, name, category (member | connection | rebar | other), representation types (stand-in signal:
  'BoundingBox' / IfcBoundingBox items = box stand-ins), expected volume in mm3:
    q   = from the product's own quantity sets (IfcQuantityVolume Net*/Gross*/Volume), unit-scaled
    an  = analytic, when the body is one IfcExtrudedAreaSolid of a standard profile without boolean cuts and the
          product has no openings (IfcRelVoidsElement; `op` = their count); hollow-rectangle corner radii and T-section
          root fillets included
Summary: counts by class and category, schema, units, georeferencing hints, external references."""
import sys, os, json, math, gzip, time, argparse, collections
import ifcopenshell
import ifcopenshell.util.unit

ap = argparse.ArgumentParser(); ap.add_argument('ifc'); ap.add_argument('out'); ap.add_argument('--parts')
a = ap.parse_args()
T0 = time.time()
CV = 3          # census version per part record: 2 = openings / HSS corner radii / T root fillets handled (grade_join trusts `an` for repeated names)
#                 3 = arbitrary profiles bounded by IfcCompositeCurve / IfcIndexedPolyCurve (lines + circular arcs, with voids) get
#                     `an`; Tekla quantities of cut parts on the exporter's sharp-corner basis rescaled (`qx`); a quantity shared
#                     by the segments of one split Revit element is not a part expectation (dropped, `qx`)
SKIP = {'IfcOpeningElement', 'IfcOpeningStandardCase', 'IfcSpace', 'IfcGrid', 'IfcAnnotation', 'IfcVirtualElement'}
MEMBER = ('IfcBeam', 'IfcColumn', 'IfcMember', 'IfcPile')
CONNECTION = ('IfcPlate', 'IfcMechanicalFastener', 'IfcFastener', 'IfcDiscreteAccessory')
REBAR = ('IfcReinforcingElement',)
SPATIAL = ('IfcSite', 'IfcBuilding', 'IfcBuildingStorey', 'IfcSpatialStructureElement', 'IfcSpatialElement')
BUILDING = ('IfcWall', 'IfcSlab', 'IfcRoof', 'IfcDoor', 'IfcWindow', 'IfcStair', 'IfcRamp', 'IfcCovering', 'IfcCurtainWall',
            'IfcFooting', 'IfcRailing', 'IfcStairFlight', 'IfcRampFlight')
MEP = ('IfcFlowSegment', 'IfcFlowFitting', 'IfcFlowTerminal', 'IfcFlowController', 'IfcDistributionElement',
       'IfcEnergyConversionDevice', 'IfcFlowMovingDevice', 'IfcFlowStorageDevice', 'IfcFlowTreatmentDevice')

LEGACY_2X3 = ('IFC2X2_FINAL', 'IFC2X_FINAL', 'IFC2X2', 'IFC2X', 'IFC2X2_PLATFORM', 'IFC2X_PLATFORM', 'IFC2X3_FINAL', 'IFC2X3_TC1',
              'IFC2X3_RC1', 'IFC2X2_RC1')     # the converters' list (ifc2step6 LEGACY_2X3 / worker fix_schema)


def open_ifc(path):
    """ifcopenshell.open; a legacy schema label (IFC2X2_FINAL ...) is read as IFC2X3 from a temporary copy in which only the
    FILE_SCHEMA string differs - the relabel the converters apply (neither kernel ships IFC2X2; before this the census of a
    reused IFC2X2_FINAL model failed on both kernels -> source_inventory_unavailable)"""
    import re, tempfile, shutil, atexit
    with open(path, 'rb') as fh:
        head = fh.read(1 << 16)
    m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", head)
    sch = m.group(1).decode('latin1').upper() if m else None
    if sch not in LEGACY_2X3:
        return ifcopenshell.open(path), None
    fd, tmp = tempfile.mkstemp(suffix='.ifc', dir=os.path.dirname(os.path.abspath(a.out)) or None)
    atexit.register(lambda: os.path.exists(tmp) and os.remove(tmp))
    with open(path, 'rb') as fi, os.fdopen(fd, 'wb') as fo:
        first = fi.read(1 << 16)
        fo.write(first[:m.start(1)] + b'IFC2X3' + first[m.end(1):])
        shutil.copyfileobj(fi, fo, 1 << 24)
    return ifcopenshell.open(tmp), sch


f, _declared = open_ifc(a.ifc)
out = {'schema': f.schema, 'parse_sec': round(time.time() - T0, 1), 'census_version': CV}
if _declared:
    out['schema_declared'] = _declared; out['schema_relabel'] = f'{_declared} read as IFC2X3 (FILE_SCHEMA label only)'


def scale(kind):
    try:
        return float(ifcopenshell.util.unit.calculate_unit_scale(f, kind))
    except Exception:
        return None


L_SI = scale('LENGTHUNIT') or 1.0                       # metres per file length unit
V_SI = scale('VOLUMEUNIT')                              # m3 per file volume unit (None: not declared -> SI m3)
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


def prof_area(pr):
    """area in file length units^2 for standard profiles; None if unknown"""
    t = pr.is_a()
    g = lambda n: getattr(pr, n, None)
    try:
        if t == 'IfcRectangleProfileDef':
            return g('XDim') * g('YDim')
        if t == 'IfcRectangleHollowProfileDef':
            x, y, w = g('XDim'), g('YDim'), g('WallThickness')
            ro, ri = g('OuterFilletRadius') or 0.0, g('InnerFilletRadius') or 0.0
            # rounded corners (every HSS / tube): each corner loses (1 - pi/4) r^2 outside and gains it back inside
            return x * y - (x - 2 * w) * (y - 2 * w) - (4 - math.pi) * (ro * ro - ri * ri)
        if t == 'IfcCircleProfileDef':
            return math.pi * g('Radius') ** 2
        if t == 'IfcCircleHollowProfileDef':
            r, w = g('Radius'), g('WallThickness')
            return math.pi * (r * r - (r - w) ** 2)
        if t == 'IfcIShapeProfileDef':
            b, h, tw, tf = g('OverallWidth'), g('OverallDepth'), g('WebThickness'), g('FlangeThickness')
            fr = g('FilletRadius') or 0.0
            return 2 * b * tf + (h - 2 * tf) * tw + (4 - math.pi) * fr * fr
        if t == 'IfcLShapeProfileDef':
            h, b, th = g('Depth'), (g('Width') or g('Depth')), g('Thickness')
            fr = g('FilletRadius') or 0.0
            return th * (h + b - th) + (1 - math.pi / 4) * fr * fr
        if t == 'IfcUShapeProfileDef':
            h, b, tw, tf = g('Depth'), g('FlangeWidth'), g('WebThickness'), g('FlangeThickness')
            return 2 * b * tf + (h - 2 * tf) * tw
        if t == 'IfcTShapeProfileDef':
            h, b, tw, tf = g('Depth'), g('FlangeWidth'), g('WebThickness'), g('FlangeThickness')
            fr = 0.0 if (g('FlangeSlope') or g('WebSlope')) else (g('FilletRadius') or 0.0)
            return b * tf + (h - tf) * tw + (2 - math.pi / 2) * fr * fr        # two web-to-flange root fillets (WT sections)
        if t == 'IfcCShapeProfileDef':
            h, w, th, gi = g('Depth'), g('Width'), g('WallThickness'), g('Girth') or 0.0
            return th * (h + 2 * w + 2 * gi - 4 * th)
        if t == 'IfcZShapeProfileDef':
            h, w, tw, tf = g('Depth'), g('FlangeWidth'), g('WebThickness'), g('FlangeThickness')
            return 2 * w * tf + (h - 2 * tf) * tw
        if pr.is_a('IfcArbitraryClosedProfileDef'):
            # v3: outer curve polyline, composite curve (polylines, trimmed circles / lines) or indexed poly curve (line +
            # arc segments) - the bounds of every Revit framing / column profile; voids (HSS) subtracted
            a_ = curve_area(pr.OuterCurve)
            if a_ is None:
                return None
            for ic in (pr.InnerCurves or []) if pr.is_a('IfcArbitraryProfileDefWithVoids') else []:
                b_ = curve_area(ic)
                if b_ is None:
                    return None
                a_ -= b_
            return a_ if a_ > 0 else None
    except Exception:
        return None
    return None


def sharp_area(pr):
    """area of a parameterized profile WITHOUT root fillets / corner radii (Tekla's basis for the NetVolume of cut parts,
    see the Tekla rule in the product loop); None when the profile has no radii (nothing to rescale) or is not handled"""
    t = pr.is_a()
    g = lambda n: getattr(pr, n, None) or 0.0
    try:
        if t == 'IfcRectangleHollowProfileDef' and (g('OuterFilletRadius') or g('InnerFilletRadius')):
            x, y, w = g('XDim'), g('YDim'), g('WallThickness')
            return x * y - (x - 2 * w) * (y - 2 * w)
        if t == 'IfcIShapeProfileDef' and g('FilletRadius'):
            return 2 * g('OverallWidth') * g('FlangeThickness') + (g('OverallDepth') - 2 * g('FlangeThickness')) * g('WebThickness')
        if t == 'IfcLShapeProfileDef' and g('FilletRadius'):
            h, th = g('Depth'), g('Thickness')
            return th * (h + (g('Width') or h) - th)
        if t == 'IfcTShapeProfileDef' and g('FilletRadius') and not (g('FlangeSlope') or g('WebSlope')):
            return g('FlangeWidth') * g('FlangeThickness') + (g('Depth') - g('FlangeThickness')) * g('WebThickness')
    except Exception:
        return None
    return None


def _pt2(p):
    c = p.Coordinates
    return float(c[0]), float(c[1])


_ANG = []


def _ang_si():
    """radians per file plane-angle unit (IfcParameterValue trims of circles)"""
    if not _ANG:
        try:
            _ANG.append(float(ifcopenshell.util.unit.calculate_unit_scale(f, 'PLANEANGLEUNIT')) or 1.0)
        except Exception:
            _ANG.append(1.0)
    return _ANG[0]


def _place2(pl):
    """IfcAxis2Placement2D -> (origin x, y, x-axis angle)"""
    o = _pt2(pl.Location)
    rd = getattr(pl, 'RefDirection', None)
    a0 = math.atan2(rd.DirectionRatios[1], rd.DirectionRatios[0]) if rd is not None else 0.0
    return o[0], o[1], a0


def _arc(cx, cy, r, t1, d):
    """Green's theorem term 1/2 (x dy - y dx) of the arc of circle (cx, cy, r) from angle t1 over signed sweep d;
    returns (term, start point, end point)"""
    t2 = t1 + d
    term = 0.5 * (r * r * d + r * cx * (math.sin(t2) - math.sin(t1)) - r * cy * (math.cos(t2) - math.cos(t1)))
    return term, (cx + r * math.cos(t1), cy + r * math.sin(t1)), (cx + r * math.cos(t2), cy + r * math.sin(t2))


def _seg_terms(c, same_sense=True):
    """one curve of a closed boundary -> (sum of Green terms, start point, end point) in traversal order, or None"""
    if c.is_a('IfcPolyline'):
        P = [_pt2(q) for q in c.Points]
        if not same_sense:
            P = P[::-1]
        return sum(0.5 * (P[i][0] * P[i + 1][1] - P[i + 1][0] * P[i][1]) for i in range(len(P) - 1)), P[0], P[-1]
    if c.is_a('IfcTrimmedCurve'):
        bc = c.BasisCurve
        def trim(sel):
            pts = [x for x in sel if hasattr(x, 'is_a') and x.is_a('IfcCartesianPoint')]
            pars = [x for x in sel if not (hasattr(x, 'is_a') and x.is_a('IfcCartesianPoint'))]
            return (_pt2(pts[0]) if pts else None), (float(getattr(pars[0], 'wrappedValue', pars[0])) if pars else None)
        (p1, u1), (p2, u2) = trim(c.Trim1), trim(c.Trim2)
        sense = bool(c.SenseAgreement) == bool(same_sense)
        if bc.is_a('IfcCircle'):
            cx, cy, a0 = _place2(bc.Position)
            r = float(bc.Radius)
            pref = str(c.MasterRepresentation) != 'PARAMETER'
            if p1 is not None and (pref or u1 is None):
                t1 = math.atan2(p1[1] - cy, p1[0] - cx)
            elif u1 is not None:
                t1 = a0 + u1 * _ang_si()
            else:
                return None
            if p2 is not None and (pref or u2 is None):
                t2 = math.atan2(p2[1] - cy, p2[0] - cx)
            elif u2 is not None:
                t2 = a0 + u2 * _ang_si()
            else:
                return None
            # the curve runs t1 -> t2 counter-clockwise when SenseAgreement, clockwise otherwise; a reversed segment
            # (SameSense false) is walked t2 -> t1 the other way round
            if not same_sense:
                t1, t2 = t2, t1
            d = (t2 - t1) % (2 * math.pi) if sense else -((t1 - t2) % (2 * math.pi))
            if abs(d) < 1e-12:
                d = 2 * math.pi if sense else -2 * math.pi
            return _arc(cx, cy, r, t1, d)
        if bc.is_a('IfcLine'):
            if p1 is None or p2 is None:
                o = _pt2(bc.Pnt); v = bc.Dir; dr = v.Orientation.DirectionRatios; m = float(v.Magnitude)
                ln = math.hypot(dr[0], dr[1]) or 1.0
                at = lambda u: (o[0] + u * m * dr[0] / ln, o[1] + u * m * dr[1] / ln)
                p1 = p1 or (at(u1) if u1 is not None else None); p2 = p2 or (at(u2) if u2 is not None else None)
                if p1 is None or p2 is None:
                    return None
            if not same_sense:
                p1, p2 = p2, p1
            return 0.5 * (p1[0] * p2[1] - p2[0] * p1[1]), p1, p2
        return None
    return None


def curve_area(c):
    """area enclosed by a closed 2D profile curve (file length units^2), None if a piece is not handled"""
    try:
        if c.is_a('IfcPolyline'):
            P = [_pt2(q) for q in c.Points]
            return abs(sum(P[i][0] * P[(i + 1) % len(P)][1] - P[(i + 1) % len(P)][0] * P[i][1] for i in range(len(P)))) / 2
        if c.is_a('IfcCircle'):
            return math.pi * float(c.Radius) ** 2
        if c.is_a('IfcCompositeCurve'):
            tot = 0.0; first = last = None
            for sg in c.Segments:
                if sg.ParentCurve is None:
                    continue                  # segment without a curve (Tekla 2017i '#0'): no geometry, as in the converter
                r_ = _seg_terms(sg.ParentCurve, bool(sg.SameSense))
                if r_ is None:
                    return None
                tot += r_[0]
                if first is None:
                    first = r_[1]
                elif math.dist(last, r_[1]) > 1e-6 * (1 + abs(last[0]) + abs(last[1])):
                    tot += 0.5 * (last[0] * r_[1][1] - r_[1][0] * last[1])        # bridge a gap between segments
                last = r_[2]
            if first is None:
                return None
            tot += 0.5 * (last[0] * first[1] - first[0] * last[1])                 # close the boundary
            return abs(tot)
        if c.is_a('IfcIndexedPolyCurve'):
            P = [(float(x[0]), float(x[1])) for x in c.Points.CoordList]
            if not c.Segments:
                return abs(sum(P[i][0] * P[(i + 1) % len(P)][1] - P[(i + 1) % len(P)][0] * P[i][1] for i in range(len(P)))) / 2
            tot = 0.0; first = last = None
            for sg in c.Segments:
                idx = [int(i) - 1 for i in sg.wrappedValue]
                kind = sg.is_a()
                if kind == 'IfcArcIndex':
                    (x1, y1), (x2, y2), (x3, y3) = P[idx[0]], P[idx[1]], P[idx[2]]
                    dd = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
                    if abs(dd) < 1e-18:
                        tot += 0.5 * (x1 * y3 - x3 * y1)
                    else:
                        ux = ((x1 * x1 + y1 * y1) * (y2 - y3) + (x2 * x2 + y2 * y2) * (y3 - y1) + (x3 * x3 + y3 * y3) * (y1 - y2)) / dd
                        uy = ((x1 * x1 + y1 * y1) * (x3 - x2) + (x2 * x2 + y2 * y2) * (x1 - x3) + (x3 * x3 + y3 * y3) * (x2 - x1)) / dd
                        r = math.hypot(x1 - ux, y1 - uy)
                        a1, a2, a3 = (math.atan2(y - uy, x - ux) for x, y in ((x1, y1), (x2, y2), (x3, y3)))
                        ccw = (a2 - a1) % (2 * math.pi) < (a3 - a1) % (2 * math.pi)
                        d = (a3 - a1) % (2 * math.pi) if ccw else -((a1 - a3) % (2 * math.pi))
                        tot += _arc(ux, uy, r, a1, d)[0]
                    pts = [P[idx[0]], P[idx[2]]]
                else:
                    pts = [P[i] for i in idx]
                    tot += sum(0.5 * (pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]) for i in range(len(pts) - 1))
                if first is None:
                    first = pts[0]
                last = pts[-1]
            tot += 0.5 * (last[0] * first[1] - first[0] * last[1])
            return abs(tot)
    except Exception:
        return None
    return None


def analytic_volume(items):
    """one IfcExtrudedAreaSolid (also through one IfcMappedItem) of a known profile, no booleans -> mm3"""
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


def single_item(items):
    """the one body item, also through one unscaled IfcMappedItem; None otherwise"""
    if len(items) != 1:
        return None
    it = items[0]
    if it.is_a('IfcMappedItem'):
        tr = it.MappingTarget
        if any(getattr(tr, n, None) not in (None, 1.0) for n in ('Scale', 'Scale2', 'Scale3')):
            return None
        src = it.MappingSource.MappedRepresentation.Items
        if len(src) != 1:
            return None
        it = src[0]
    return it


def material_extrusions(it, depth=0):
    """the extrusions that carry material in a boolean tree (DIFFERENCE: its first operand, UNION: both), plus whether a
    UNION occurs; None when another operator / operand kind is met"""
    if depth > 256:
        return None
    if it.is_a('IfcBooleanResult'):
        op = str(it.Operator)
        if op == 'DIFFERENCE':
            return material_extrusions(it.FirstOperand, depth + 1)
        if op == 'UNION':
            a_ = material_extrusions(it.FirstOperand, depth + 1); b_ = material_extrusions(it.SecondOperand, depth + 1)
            return None if a_ is None or b_ is None else (a_[0] + b_[0], True)
        return None
    return ([it], False) if it.is_a('IfcExtrudedAreaSolid') else None


def cut_base(items):
    """v3: a body that is one cut part - IfcBooleanResult / IfcBooleanClippingResult with DIFFERENCE all along the first
    operand (also through one unscaled IfcMappedItem) - ending in one IfcExtrudedAreaSolid -> that extrusion, else None"""
    it = single_item(items)
    if it is None:
        return None
    n = 0
    while it.is_a('IfcBooleanResult') and n < 256:
        if str(it.Operator) != 'DIFFERENCE':
            return None
        it = it.FirstOperand; n += 1
    return it if n and it.is_a('IfcExtrudedAreaSolid') else None


try:
    APPS = ' '.join((x.ApplicationFullName or '') + ' ' + (x.ApplicationIdentifier or '') for x in f.by_type('IfcApplication'))
except Exception:
    APPS = ''
TEKLA = 'tekla' in APPS.lower()
REVIT = 'revit' in APPS.lower()
by_cls = collections.Counter(); by_cat = collections.Counter(); reptypes = collections.Counter()
standins = collections.Counter(); no_body = collections.Counter(); skipped = collections.Counter()
n_qx = collections.Counter()
parts = []; n_an = n_q = 0
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
    if box:
        rec['standin'] = 'bounding_box'
    n_op = sum(1 for r in (getattr(p, 'HasOpenings', None) or []) if r.is_a('IfcRelVoidsElement'))
    if n_op:
        rec['op'] = n_op                                  # openings (bolt holes, copes) are cut from the body
    av = analytic_volume(items) if not n_op else None     # profile area x depth would ignore the voids -> no analytic value
    if av:
        rec['an'] = round(av[0], 1); rec['pt'] = av[1][3:-10] if av[1].endswith('ProfileDef') else av[1]; n_an += 1
    qv = quantity_volume(p)
    if REVIT and qv:
        rec['_qraw'] = (qv['kind'], round(qv['mm3'], 0))      # before the openings rule (split-element check below)
    if qv and n_op and qv['kind'] in ('gross', 'weight'):
        qv = None                                         # gross quantities exclude the openings too
    if qv and TEKLA and qv['kind'] == 'net':
        # Tekla computes NetVolume of a CUT part on its profile without root fillets / corner radii, while the exported
        # body carries them (IShape FilletRadius, RHS corner radii, L / T fillets): measured on 4 Tekla models (2017i,
        # 21.1 SR8 / SR10), cut W / RHS parts 0.908 .. 1.083 x the body, exactly A(radii) / A(sharp) of the profile;
        # uncut parts (and parts with openings only) carry the body volume. Rescaled by the profile's own parameters.
        b_ = cut_base(items)
        if b_ is not None:
            sa, ra = sharp_area(b_.SweptArea), prof_area(b_.SweptArea)
            if sa and ra and sa > 0:
                rec['q0'] = round(qv['mm3'], 1); rec['qx'] = 'tekla_cut_part_sharp_profile_basis'
                qv = dict(qv, mm3=qv['mm3'] * ra / sa); n_qx[rec['qx']] += 1
        else:
            # round bars joined with UNION (sag rods, anchor bolts: rod + threaded ends): NetVolume is taken on inscribed
            # polygons whose side count depends on the diameter (measured 0.9003 = 8-gon on 1/2..5/8" sag rods, 0.9549 =
            # 12-gon on 1 1/2" anchor bolts, Tekla 2017i) -> not a +-5 % expectation; dropped (kept as q0)
            top = single_item(items)
            me = material_extrusions(top) if top is not None and top.is_a('IfcBooleanResult') else None
            if me and me[1] and all(e_.SweptArea.is_a() == 'IfcCircleProfileDef' for e_ in me[0]):
                rec['q0'] = round(qv['mm3'], 1); rec['qx'] = 'tekla_union_round_bar_polygon_basis'
                qv = None; n_qx[rec['qx']] += 1
    if qv:
        rec['q'] = round(qv['mm3'], 1); rec['qk'] = qv['kind']; n_q += 1
    parts.append(rec)
if REVIT:
    # Revit "split walls and columns by level": every segment repeats the whole element's BaseQuantities (same name with
    # the element id suffix ':<id>', same value) -> the quantity is not the segment's volume (measured 0.03 .. 0.88 per
    # segment, 1.03 .. 1.06 for the sum of a column's segments) -> no quantity expectation for those segments
    import re as _re
    grp = collections.defaultdict(list)
    for r_ in parts:
        if r_.get('_qraw') and r_.get('name') and _re.search(r':\d+$', str(r_['name'])):
            grp[(r_['name'],) + r_['_qraw']].append(r_)          # raw quantity: a segment with openings counts too
    for k_, lst in grp.items():
        if len(lst) >= 2:
            for r_ in lst:
                if 'q' in r_:
                    r_['q0'] = r_.pop('q'); r_['qx'] = 'revit_split_element_shared_quantity'; r_.pop('qk', None)
                    n_q -= 1; n_qx[r_['qx']] += 1
for r_ in parts:
    r_.pop('_qraw', None)
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
            'with_quantity_volume': n_q, 'quantities_rebased': dict(n_qx), 'external_refs': ext, 'applications': apps, 'sec': round(time.time() - T0, 1)})
if a.parts:
    with gzip.open(a.parts, 'wt') as g:
        for r in parts:
            g.write(json.dumps(r) + '\n')
json.dump(out, open(a.out, 'w'))
print(json.dumps(out))
