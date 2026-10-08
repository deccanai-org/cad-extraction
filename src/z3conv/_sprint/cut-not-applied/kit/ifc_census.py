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
CV = 2          # census version per part record: 2 = openings / HSS corner radii / T root fillets handled (grade_join trusts `an` for repeated names)
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
        if t == 'IfcArbitraryClosedProfileDef' and not pr.is_a('IfcArbitraryProfileDefWithVoids'):
            c = pr.OuterCurve
            if c.is_a('IfcPolyline'):
                P = [tuple(q.Coordinates[:2]) for q in c.Points]
                return abs(sum(P[i][0] * P[(i + 1) % len(P)][1] - P[(i + 1) % len(P)][0] * P[i][1] for i in range(len(P)))) / 2
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


by_cls = collections.Counter(); by_cat = collections.Counter(); reptypes = collections.Counter()
standins = collections.Counter(); no_body = collections.Counter(); skipped = collections.Counter()
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
            'with_quantity_volume': n_q, 'external_refs': ext, 'applications': apps, 'sec': round(time.time() - T0, 1)})
if a.parts:
    with gzip.open(a.parts, 'wt') as g:
        for r in parts:
            g.write(json.dumps(r) + '\n')
json.dump(out, open(a.out, 'w'))
print(json.dumps(out))
