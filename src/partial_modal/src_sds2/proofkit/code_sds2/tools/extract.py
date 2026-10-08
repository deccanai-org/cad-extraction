#!/usr/bin/env python3
"""IFC -> construction schedules for a parametric build123d rebuild.

Reads one IFC model and writes the tables the build script constructs the model from (all lengths in millimetres,
all positions in model coordinates):

  parts.csv        every part: GlobalId, IFC class, role (member/plate/bolt/weld/accessory/concrete/other), name, marks,
                   profile designation, material, how its geometry is defined (parametric / exact)
  profiles.csv     every cross-section once: kind (I, U, L, RECT, RHS, CIRCLE, CHS, POLY) and its dimensions
  profile_outlines.json   outlines of POLY profiles (lines, three-point arcs and elliptical arcs: {"t": "E", "p": [start,
                   mid, end], "c": centre, "x": unit direction of the first semi-axis, "r": [semi-axis 1, semi-axis 2]},
                   which a builder without elliptical arcs would read as the circular arc through p - see _ellipse)
  solids.csv       every extruded solid: part, role (body / cut tool / opening tool), profile, placement frame,
                   extrusion vector, axes of the frame its representation is defined in
  cuts.csv         every cut on a body solid: plane cut, plane cut bounded by a polygon, or a cutting solid
  cut_boundaries.json     polygons of bounded plane cuts
  openings.csv     openings (holes, copes) subtracted from a whole part, with their tool solids
  assembly_tree.csv       every assembly (IfcElementAssembly) with its parent assembly and nesting depth, including
                   assemblies whose only members are other assemblies (views.py merges it into assemblies.csv)
  exact_ifc.jsonl  the polygon faces of parts the source holds only as faceted surfaces (no parameters), read at full
                   precision from the IFC's own IfcFacetedBrep / IfcFacetedBrepWithVoids / IfcShellBasedSurfaceModel /
                   IfcFaceBasedSurfaceModel / IfcPolygonalFaceSet / IfcTriangulatedFaceSet items (through mapped items,
                   placements and the file's length unit). exact.py turns them into exact_geometry.jsonl and takes the
                   delivered model's faces instead for any part this route cannot give exactly (see faceted_defect)

Semantics follow IFC2x3/IFC4 as implemented by the IfcOpenShell geometry kernel, which produced the delivered STEP;
verify.py checks every part against both.
"""
import csv, json, math, os, sys, zipfile, tempfile, collections, re
import numpy as np
import ifcopenshell

SDS2_EMITTER = 'z3-sds2-ifc-emitter'     # FILE_NAME originating system of the IFC tools/sds2ifc writes from an SDS/2 conversion
SKIP_CLASSES = ('IfcOpeningElement', 'IfcSpatialStructureElement', 'IfcGrid', 'IfcAnnotation', 'IfcSpace',
                'IfcVirtualElement', 'IfcSpatialElement')
BODY_IDS = ('Body', 'Facetation', None, '')


def open_ifc(path):
    if path.lower().endswith('zip'):
        z = zipfile.ZipFile(path)
        n = [x for x in z.namelist() if x.lower().endswith('.ifc')][0]
        d = tempfile.mkdtemp()
        z.extract(n, d)
        return ifcopenshell.open(os.path.join(d, n))
    return ifcopenshell.open(path)


class Unsupported(Exception):
    pass


# ------------------------------------------------------------------------------------------------ units
def unit_factors(f):
    """(length -> mm, plane angle -> radians)"""
    PREFIX = {None: 1.0, 'EXA': 1e18, 'PETA': 1e15, 'TERA': 1e12, 'GIGA': 1e9, 'MEGA': 1e6, 'KILO': 1e3, 'HECTO': 1e2,
              'DECA': 1e1, 'DECI': 1e-1, 'CENTI': 1e-2, 'MILLI': 1e-3, 'MICRO': 1e-6, 'NANO': 1e-9}
    def si_value(u):
        return PREFIX[u.Prefix] if u.is_a('IfcSIUnit') else None
    length, angle = 1.0, 1.0
    ua = f.by_type('IfcUnitAssignment')
    for u in (ua[0].Units if ua else []):
        ut = getattr(u, 'UnitType', None)
        if ut == 'LENGTHUNIT':
            if u.is_a('IfcSIUnit'):
                length = PREFIX[u.Prefix] * 1000.0
            elif u.is_a('IfcConversionBasedUnit'):
                cf = u.ConversionFactor
                base = si_value(cf.UnitComponent) if cf.UnitComponent.is_a('IfcSIUnit') else 1.0
                length = float(cf.ValueComponent.wrappedValue) * base * 1000.0
        elif ut == 'PLANEANGLEUNIT':
            if u.is_a('IfcSIUnit'):
                angle = 1.0
            elif u.is_a('IfcConversionBasedUnit'):
                angle = float(u.ConversionFactor.ValueComponent.wrappedValue)
    return length, angle


# ------------------------------------------------------------------------------------------------ geometry helpers
def unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    if n < 1e-15:
        raise Unsupported('zero-length direction')
    return v / n


class Ctx:
    def __init__(self, f):
        self.f = f
        self.L, self.A = unit_factors(f)
        self._plc = {}

    # 3D placement -> 4x4
    def ax3(self, p):
        if p is None:
            return np.eye(4)
        if p.is_a('IfcAxis2Placement2D'):
            m2 = self.ax2(p)
            m = np.eye(4)
            m[:2, :2] = m2[:2, :2]
            m[:2, 3] = m2[:2, 2]
            return m
        loc = np.array(list(p.Location.Coordinates) + [0.0] * (3 - len(p.Location.Coordinates))) * self.L
        z = unit(p.Axis.DirectionRatios) if p.Axis else np.array([0.0, 0.0, 1.0])
        if p.RefDirection:
            x = np.asarray(p.RefDirection.DirectionRatios, float)
        else:
            x = np.array([1.0, 0.0, 0.0]) if abs(z[0]) < 1 - 1e-12 else np.array([0.0, 1.0, 0.0])  # IfcFirstProjAxis
        x = x - np.dot(x, z) * z
        if np.linalg.norm(x) < 1e-12:
            x = np.array([1.0, 0.0, 0.0]) if abs(z[0]) < 1 - 1e-9 else np.array([0.0, 1.0, 0.0])
            x = x - np.dot(x, z) * z
        x = unit(x)
        y = np.cross(z, x)
        m = np.eye(4)
        m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x, y, z, loc
        return m

    # 2D placement -> 3x3
    def ax2(self, p):
        m = np.eye(3)
        if p is None:
            return m
        loc = np.array(p.Location.Coordinates[:2], float) * self.L
        x = unit(p.RefDirection.DirectionRatios[:2]) if getattr(p, 'RefDirection', None) else np.array([1.0, 0.0])
        m[:2, 0], m[:2, 1], m[:2, 2] = x, (-x[1], x[0]), loc
        return m

    def placement(self, op):
        if op is None:
            return np.eye(4)
        k = op.id()
        if k in self._plc:
            return self._plc[k]
        if op.is_a('IfcLocalPlacement'):
            parent = self.placement(op.PlacementRelTo) if op.PlacementRelTo else np.eye(4)
            m = parent @ self.ax3(op.RelativePlacement)
        else:
            raise Unsupported('placement ' + op.is_a())
        self._plc[k] = m
        return m

    # IfcCartesianTransformationOperator3D -> 4x4 (IfcBaseAxis)
    def cto3(self, t):
        if t is None:
            return np.eye(4)
        if t.is_a('IfcCartesianTransformationOperator2D'):
            raise Unsupported('2D transformation operator on 3D mapped item')
        z = unit(t.Axis3.DirectionRatios) if t.Axis3 else np.array([0.0, 0.0, 1.0])
        if t.Axis1:
            v = np.asarray(t.Axis1.DirectionRatios, float)
        else:
            v = np.array([1.0, 0.0, 0.0]) if not np.allclose(z, [1.0, 0.0, 0.0]) else np.array([0.0, 1.0, 0.0])
        x = unit(v - np.dot(v, z) * z)
        yv = np.asarray(t.Axis2.DirectionRatios, float) if t.Axis2 else np.array([0.0, 1.0, 0.0])
        y = yv - np.dot(yv, z) * z
        y = unit(y - np.dot(y, x) * x)
        s1 = t.Scale if t.Scale is not None else 1.0
        s2 = getattr(t, 'Scale2', None)
        s3 = getattr(t, 'Scale3', None)
        s2 = s1 if s2 is None else s2
        s3 = s1 if s3 is None else s3
        m = np.eye(4)
        m[:3, 0], m[:3, 1], m[:3, 2] = x * s1, y * s2, z * s3
        m[:3, 3] = np.array(list(t.LocalOrigin.Coordinates) + [0.0] * (3 - len(t.LocalOrigin.Coordinates))) * self.L
        return m


def rigid_and_scale(m):
    """split a 4x4 into (orthonormal rotation, uniform scale); Unsupported for shear / non-uniform scale"""
    r = m[:3, :3]
    s = np.linalg.norm(r, axis=0)
    if np.max(np.abs(s - s[0])) > 1e-9 * max(1.0, s[0]):
        raise Unsupported('non-uniform scale')
    rn = r / s[0]
    if np.max(np.abs(rn.T @ rn - np.eye(3))) > 1e-7:
        raise Unsupported('shear in transform')
    if np.linalg.det(rn) < 0:
        raise Unsupported('mirroring transform')
    return rn, float(s[0])


# ------------------------------------------------------------------------------------------------ profiles
def _r(v):
    v = float(f'{v:.12g}')
    return 0.0 if abs(v) < 1e-9 else v


def _rp(v):
    """profile parameters / in-profile positions: 1e-9 mm grid so that float noise does not split equal profiles"""
    v = round(float(v), 9)
    return 0.0 if abs(v) < 1e-9 else v


class Profiles:
    """dedups profiles; parameterized profiles keep their parameters, curve-bounded ones become POLY outlines"""
    def __init__(self, ctx):
        self.ctx = ctx
        self.rows = []
        self.outlines = {}
        self._key = {}

    def add(self, pd):
        row, outline = self.describe(pd)
        key = json.dumps([row, outline], sort_keys=True)
        if key in self._key:
            return self._key[key]
        pid = f'P{len(self.rows) + 1}'
        row = dict(profile_id=pid, **row)
        self.rows.append(row)
        if outline is not None:
            self.outlines[pid] = outline
        self._key[key] = pid
        return pid

    def describe(self, pd):
        L, A = self.ctx.L, self.ctx.A
        name = getattr(pd, 'ProfileName', None) or ''
        pos = None
        if pd.is_a('IfcParameterizedProfileDef'):
            p = getattr(pd, 'Position', None)
            if p is not None:
                m = self.ctx.ax2(p)
                ang = math.atan2(m[1, 0], m[0, 0])
                pos = (m[0, 2], m[1, 2], ang)
        base = dict(designation=name, pos_x=_rp(pos[0]) if pos else 0.0, pos_y=_rp(pos[1]) if pos else 0.0,
                    pos_angle=_rp(pos[2]) if pos else 0.0)
        g = lambda a: None if getattr(pd, a, None) is None else _rp(getattr(pd, a) * L)
        if pd.is_a('IfcIShapeProfileDef'):
            if getattr(pd, 'FlangeSlope', None) or getattr(pd, 'FlangeEdgeRadius', None):
                raise Unsupported('I profile with flange slope / edge radius')
            return dict(kind='I', d=g('OverallDepth'), b=g('OverallWidth'), tw=g('WebThickness'), tf=g('FlangeThickness'),
                        r=g('FilletRadius') or 0.0, **base), None
        if pd.is_a('IfcUShapeProfileDef'):
            slope = getattr(pd, 'FlangeSlope', None)
            return dict(kind='U', d=g('Depth'), b=g('FlangeWidth'), tw=g('WebThickness'), tf=g('FlangeThickness'),
                        r=g('FilletRadius') or 0.0, r_edge=g('EdgeRadius') or 0.0,
                        slope=_r(slope * A) if slope else 0.0, **base), None
        if pd.is_a('IfcLShapeProfileDef'):
            slope = getattr(pd, 'LegSlope', None)
            return dict(kind='L', d=g('Depth'), b=g('Width') if pd.Width is not None else g('Depth'), t=g('Thickness'),
                        r=g('FilletRadius') or 0.0, r_edge=g('EdgeRadius') or 0.0,
                        slope=_r(slope * A) if slope else 0.0, **base), None
        if pd.is_a('IfcRectangleHollowProfileDef'):
            return dict(kind='RHS', b=g('XDim'), d=g('YDim'), t=g('WallThickness'), r_inner=g('InnerFilletRadius') or 0.0,
                        r_outer=g('OuterFilletRadius') or 0.0, **base), None
        if pd.is_a('IfcRoundedRectangleProfileDef'):
            return dict(kind='RECT', b=g('XDim'), d=g('YDim'), r_outer=g('RoundingRadius') or 0.0, **base), None
        if pd.is_a('IfcRectangleProfileDef'):
            return dict(kind='RECT', b=g('XDim'), d=g('YDim'), **base), None
        if pd.is_a('IfcCircleHollowProfileDef'):
            return dict(kind='CHS', radius=g('Radius'), t=g('WallThickness'), **base), None
        if pd.is_a('IfcCircleProfileDef'):
            return dict(kind='CIRCLE', radius=g('Radius'), **base), None
        if pd.is_a('IfcArbitraryClosedProfileDef'):
            outer = self.curve(pd.OuterCurve)
            inner = [self.curve(c) for c in pd.InnerCurves] if pd.is_a('IfcArbitraryProfileDefWithVoids') else []
            return dict(kind='POLY', **base), {'outer': outer, 'inner': inner}
        raise Unsupported('profile ' + pd.is_a())

    # ---- curves -> list of segments {"t": "L", "p": [[x, y], ...]} | {"t": "A", "p": [start, mid, end]}
    def curve(self, c):
        segs = self._curve(c)
        return close_segments(segs)

    def _pts(self, pts):
        L = self.ctx.L
        return [[_r(p.Coordinates[0] * L), _r(p.Coordinates[1] * L)] for p in pts]

    def _curve(self, c, sense=True):
        if c.is_a('IfcPolyline'):
            pts = self._pts(c.Points)
            if not sense:
                pts = pts[::-1]
            return [{'t': 'L', 'p': pts}]
        if c.is_a('IfcCompositeCurve'):
            out = []
            for s in c.Segments:
                out += self._curve(s.ParentCurve, s.SameSense)
            return out if sense else reverse_segments(out)
        if c.is_a('IfcTrimmedCurve'):
            return self._trimmed(c, sense)
        if c.is_a('IfcCircle'):
            m = self.ctx.ax2(c.Position)
            R = c.Radius * self.ctx.L
            ctr, x, y = m[:2, 2], m[:2, 0], m[:2, 1]
            P = lambda t: [_r(v) for v in ctr + R * (math.cos(t) * x + math.sin(t) * y)]
            segs = [{'t': 'A', 'p': [P(0), P(math.pi / 2), P(math.pi)]}, {'t': 'A', 'p': [P(math.pi), P(3 * math.pi / 2), P(2 * math.pi)]}]
            return segs if sense else reverse_segments(segs)
        if c.is_a('IfcEllipse'):
            E = self._ellipse(c)
            segs = [E(0.0, math.pi), E(math.pi, 2 * math.pi)]
            return segs if sense else reverse_segments(segs)
        if c.is_a('IfcIndexedPolyCurve'):
            pts = [[_r(v * self.ctx.L) for v in p[:2]] for p in c.Points.CoordList]
            segs = []
            if c.Segments:
                for s in c.Segments:
                    idx = [i - 1 for i in s.wrappedValue]
                    if s.is_a('IfcLineIndex'):
                        segs.append({'t': 'L', 'p': [pts[i] for i in idx]})
                    else:
                        segs.append({'t': 'A', 'p': [pts[i] for i in idx]})
            else:
                segs = [{'t': 'L', 'p': pts}]
            return segs if sense else reverse_segments(segs)
        raise Unsupported('curve ' + c.is_a())

    def _trimmed(self, c, sense):
        b = c.BasisCurve
        L, A = self.ctx.L, self.ctx.A
        cart_first = c.MasterRepresentation != 'PARAMETER'
        def pick(trims):
            pt = next((t for t in trims if t.is_a('IfcCartesianPoint')), None)
            pv = next((t for t in trims if t.is_a('IfcParameterValue')), None)
            if cart_first and pt is not None:
                return 'pt', pt
            if pv is not None:
                return 'pv', pv.wrappedValue
            if pt is not None:
                return 'pt', pt
            raise Unsupported('trim without value')
        t1, t2 = pick(c.Trim1), pick(c.Trim2)
        if b.is_a('IfcCircle'):
            m = self.ctx.ax2(b.Position)
            R = b.Radius * L
            ctr, x, y = m[:2, 2], m[:2, 0], m[:2, 1]
            def ang(t):
                if t[0] == 'pv':
                    return t[1] * A
                q = np.array(t[1].Coordinates[:2], float) * L - ctr
                return math.atan2(np.dot(q, y), np.dot(q, x))
            a1, a2 = ang(t1), ang(t2)
            if c.SenseAgreement:
                sweep = (a2 - a1) % (2 * math.pi)
            else:
                sweep = -((a1 - a2) % (2 * math.pi))
            if abs(sweep) < 1e-12:
                sweep = 2 * math.pi if c.SenseAgreement else -2 * math.pi
            P = lambda t: [_r(v) for v in ctr + R * (math.cos(t) * x + math.sin(t) * y)]
            if abs(sweep) > math.pi * 1.5:   # split long arcs so each three-point arc is well conditioned
                segs = [{'t': 'A', 'p': [P(a1), P(a1 + sweep / 4), P(a1 + sweep / 2)]},
                        {'t': 'A', 'p': [P(a1 + sweep / 2), P(a1 + 3 * sweep / 4), P(a1 + sweep)]}]
            else:
                segs = [{'t': 'A', 'p': [P(a1), P(a1 + sweep / 2), P(a1 + sweep)]}]
            return segs if sense else reverse_segments(segs)
        if b.is_a('IfcLine'):
            p0 = np.array(b.Pnt.Coordinates[:2], float) * L
            v = np.array(b.Dir.Orientation.DirectionRatios[:2], float)
            v = v / np.linalg.norm(v) * b.Dir.Magnitude * L
            def pt(t):
                if t[0] == 'pt':
                    return [_r(q * L) for q in t[1].Coordinates[:2]]
                return [_r(q) for q in p0 + v * t[1] / L * 1.0]   # parameter in length units of the vector magnitude
            pts = [pt(t1), pt(t2)]
            if not c.SenseAgreement:
                pass  # a line segment between the trims is the same either way
            seg = [{'t': 'L', 'p': pts}]
            return seg if sense else reverse_segments(seg)
        if b.is_a('IfcEllipse'):
            m = self.ctx.ax2(b.Position)
            R1, R2 = b.SemiAxis1 * L, b.SemiAxis2 * L
            ctr, x, y = m[:2, 2], m[:2, 0], m[:2, 1]
            def ang(t):
                """ellipse parameter (IFC: P(t) = centre + SemiAxis1 cos(t) x + SemiAxis2 sin(t) y)"""
                if t[0] == 'pv':
                    return t[1] * A
                q = np.array(t[1].Coordinates[:2], float) * L - ctr
                return math.atan2(np.dot(q, y) / R2, np.dot(q, x) / R1)
            a1, a2 = ang(t1), ang(t2)
            if c.SenseAgreement:
                sweep = (a2 - a1) % (2 * math.pi)
            else:
                sweep = -((a1 - a2) % (2 * math.pi))
            if abs(sweep) < 1e-12:
                sweep = 2 * math.pi if c.SenseAgreement else -2 * math.pi
            E = self._ellipse(b)
            if abs(sweep) > math.pi * 1.5:   # split long arcs as for circles
                segs = [E(a1, a1 + sweep / 2), E(a1 + sweep / 2, a1 + sweep)]
            else:
                segs = [E(a1, a1 + sweep)]
            return segs if sense else reverse_segments(segs)
        raise Unsupported('trimmed ' + b.is_a())

    def _ellipse(self, b):
        """IfcEllipse -> f(t0, t1): elliptical arc segment from parameter t0 to t1 (radians, either direction):
        {"t": "E", "p": [start, mid, end], "c": centre, "x": unit direction of SemiAxis1, "r": [SemiAxis1, SemiAxis2]}"""
        L = self.ctx.L
        m = self.ctx.ax2(b.Position)
        R1, R2 = b.SemiAxis1 * L, b.SemiAxis2 * L
        if R1 <= 0 or R2 <= 0:
            raise Unsupported('degenerate IfcEllipse')
        ctr, x, y = m[:2, 2], m[:2, 0], m[:2, 1]
        P = lambda t: [_r(v) for v in ctr + R1 * math.cos(t) * x + R2 * math.sin(t) * y]
        return lambda t0, t1: {'t': 'E', 'p': [P(t0), P((t0 + t1) / 2), P(t1)], 'c': [_r(ctr[0]), _r(ctr[1])],
                               'x': [_r(x[0]), _r(x[1])], 'r': [_r(R1), _r(R2)]}


def reverse_segments(segs):
    return [dict(s, p=s['p'][::-1]) for s in segs[::-1]]


def close_segments(segs, snap=1e-3):
    """join consecutive segments end-to-start (snapping gaps below `snap` mm, bridging larger gaps with a line) and
    close the loop; drops zero-length line pieces"""
    out = []
    cur = None
    for s in segs:
        p = [list(q) for q in s['p']]
        if s['t'] == 'L':
            p = [q for i, q in enumerate(p) if i == 0 or math.dist(q, p[i - 1]) > 1e-9]
            if len(p) < 2:
                continue
        if cur is not None:
            gap = math.dist(cur, p[0])
            if gap <= snap:
                p[0] = cur
            else:
                out.append({'t': 'L', 'p': [cur, p[0]]})
        out.append(dict(s, p=p))              # keeps the segment's other keys (ellipse parameters)
        cur = p[-1]
    if not out:
        raise Unsupported('empty curve')
    start = out[0]['p'][0]
    if math.dist(cur, start) > snap:
        out.append({'t': 'L', 'p': [cur, start]})
    else:
        out[-1]['p'][-1] = start
    return out


# ------------------------------------------------------------------------------------------------ items -> solids / cuts
class Model:
    def __init__(self, f):
        self.f = f
        self.ctx = Ctx(f)
        self.prof = Profiles(self.ctx)
        self.solids = []      # rows
        self.cuts = []
        self.bounds = {}
        self.openings = []

    def new_solid(self, part_id, role, item, T, opening_id=''):
        """IfcExtrudedAreaSolid under transform T (4x4, item coordinates -> model mm)"""
        if not item.is_a('IfcExtrudedAreaSolid'):
            raise Unsupported('solid ' + item.is_a())
        P = T @ self.ctx.ax3(item.Position)
        R, s = rigid_and_scale(P)
        d = np.asarray(item.ExtrudedDirection.DirectionRatios, float)
        d = d / np.linalg.norm(d)
        vec = (P[:3, :3] @ d) * item.Depth * self.ctx.L           # includes the uniform scale
        pid = self.prof.add(item.SweptArea)
        sid = f'S{len(self.solids) + 1}'
        o, x, z = P[:3, 3], R[:, 0], R[:, 2]
        # axes of the coordinate system the solid's representation is defined in (the product's placement, or a mapped
        # representation): the IfcOpenShell kernel evaluates the representation's booleans there, and its bounding box
        # tests (half space cuts) are axis-aligned in that frame
        fx, fz = unit(T[:3, 0]), unit(T[:3, 2])
        self.solids.append(dict(solid_id=sid, part_id=part_id, role=role, opening_id=opening_id, profile_id=pid,
                                ox=_r(o[0]), oy=_r(o[1]), oz=_r(o[2]), xx=_r(x[0]), xy=_r(x[1]), xz=_r(x[2]),
                                zx=_r(z[0]), zy=_r(z[1]), zz=_r(z[2]), vx=_r(vec[0]), vy=_r(vec[1]), vz=_r(vec[2]),
                                scale=_r(s), fxx=_r(fx[0]), fxy=_r(fx[1]), fxz=_r(fx[2]), fzx=_r(fz[0]), fzy=_r(fz[1]),
                                fzz=_r(fz[2])))
        return sid

    def plane_world(self, pos, T):
        P = T @ self.ctx.ax3(pos)
        R, s = rigid_and_scale(P)
        return P[:3, 3], R[:, 2]

    def item(self, part_id, role, it, T, opening_id=''):
        """returns list of body solid ids created for this item"""
        if it.is_a('IfcMappedItem'):
            src = it.MappingSource
            M = T @ self.ctx.cto3(it.MappingTarget) @ self.ctx.ax3(src.MappingOrigin)
            out = []
            for sub in src.MappedRepresentation.Items:
                out += self.item(part_id, role, sub, M, opening_id)
            return out
        if it.is_a('IfcExtrudedAreaSolid'):
            return [self.new_solid(part_id, role, it, T, opening_id)]
        if it.is_a('IfcBooleanResult'):       # includes IfcBooleanClippingResult
            if it.Operator != 'DIFFERENCE':
                raise Unsupported('boolean ' + it.Operator)
            base = self.item(part_id, role, it.FirstOperand, T, opening_id)
            if len(base) != 1:
                raise Unsupported('boolean with compound first operand')
            self.cut(base[0], it.SecondOperand, T)
            return base
        raise Unsupported('item ' + it.is_a())

    def cut(self, target_sid, op, T):
        cid = f'C{len(self.cuts) + 1}'
        row = dict(cut_id=cid, solid_id=target_sid)
        if op.is_a('IfcHalfSpaceSolid'):
            surf = op.BaseSurface
            if not surf.is_a('IfcPlane'):
                raise Unsupported('half space on ' + surf.is_a())
            o, n = self.plane_world(surf.Position, T)
            keep = n if op.AgreementFlag else -n                   # material of the half space lies against its normal
            row.update(kind='plane' if not op.is_a('IfcPolygonalBoundedHalfSpace') else 'bounded_plane',
                       px=_r(o[0]), py=_r(o[1]), pz=_r(o[2]), nx=_r(keep[0]), ny=_r(keep[1]), nz=_r(keep[2]), tool_solid_id='')
            if op.is_a('IfcPolygonalBoundedHalfSpace'):
                P = T @ self.ctx.ax3(op.Position)
                R, s = rigid_and_scale(P)
                outline = self.prof.curve(op.PolygonalBoundary)
                self.bounds[cid] = {'frame': {'o': [_r(v) for v in P[:3, 3]], 'x': [_r(v) for v in R[:, 0]],
                                              'z': [_r(v) for v in R[:, 2]], 'scale': _r(s)}, 'outline': outline}
            self.cuts.append(row)
            return
        if op.is_a('IfcExtrudedAreaSolid') or op.is_a('IfcBooleanResult') or op.is_a('IfcMappedItem'):
            tools = self.item(self.solids[int(target_sid[1:]) - 1]['part_id'], 'cut_tool', op, T)
            for t in tools:
                self.cuts.append(dict(cut_id=f'C{len(self.cuts) + 1}', solid_id=target_sid, kind='solid', px='', py='', pz='',
                                      nx='', ny='', nz='', tool_solid_id=t))
            return
        raise Unsupported('cut operand ' + op.is_a())

    # ---- IFC emitted from an SDS/2 conversion (z3-sds2-ifc-emitter): a part's items are faceted B-reps of SDS/2's pieces,
    # extrusions (rods, studs, bolt shanks) and DIFFERENCE chains of either minus hole tools (extrusions)
    def sds2_part(self, part_id, rep, T):
        """the items of one product of an SDS/2-emitted IFC (through mapped items): an IfcExtrudedAreaSolid is a body
        solid (its own DIFFERENCE chain, if any, becomes its cuts); an IfcFacetedBrep gives exact faces (returned), and the
        tools of its DIFFERENCE chain (IfcExtrudedAreaSolid hole tools, the same entities on every faceted item of the
        part) one opening of the part whose tool solids steelbuild subtracts from the part's solids. Unsupported for any
        other item, or for faceted items with different tool sets"""
        flat = []

        def walk(it, Tm):
            if it.is_a('IfcMappedItem'):
                src = it.MappingSource
                M = Tm @ self.ctx.cto3(it.MappingTarget) @ self.ctx.ax3(src.MappingOrigin)
                for sub in src.MappedRepresentation.Items:
                    walk(sub, M)
            else:
                flat.append((it, Tm))
        for it in rep.Items:
            walk(it, T)
        faceted, tool_sets = [], []
        for it, Ti in flat:
            chain, base = [], it
            while base.is_a('IfcBooleanResult'):                 # iterative: chains hold hundreds of holes
                if base.Operator != 'DIFFERENCE':
                    raise Unsupported('boolean ' + base.Operator)
                chain.append(base.SecondOperand)
                base = base.FirstOperand
            chain.reverse()
            if base.is_a('IfcExtrudedAreaSolid'):
                sid = self.new_solid(part_id, 'body', base, Ti)
                for op in chain:
                    self.cut(sid, op, Ti)
                tool_sets.append(None)
            elif base.is_a('IfcFacetedBrep') and not base.is_a('IfcFacetedBrepWithVoids'):
                faceted += self.faceted(base, Ti)
                for op in chain:
                    if not op.is_a('IfcExtrudedAreaSolid'):
                        raise Unsupported('hole tool ' + op.is_a())
                tool_sets.append(([op.id() for op in chain], chain, Ti))
            else:
                raise Unsupported('sds2 item ' + base.is_a())
        cut = [t for t in tool_sets if t is not None and t[0]]
        if cut:
            if any(t is None or t[0] != cut[0][0] for t in tool_sets):
                raise Unsupported('items with different hole tools')
            oid = f'O{len(self.openings) + 1}'
            tools = [self.new_solid(part_id, 'opening_tool', op, cut[0][2], opening_id=oid) for op in cut[0][1]]
            self.openings.append(dict(opening_id=oid, part_id=part_id, opening_guid=part_id + ':holes', tool_solids=' '.join(tools)))
        return faceted

    # ---- faceted surfaces, read from the IFC entities at full precision (the faces of 'exact' parts)
    def faceted(self, it, T):
        """the faceted solids of one representation item in model mm, as the IFC states them:
        [{'faces': [[outer loop, hole loop, ...], ...], 'voids': [[faces of a void shell], ...]}]. Unsupported for an
        item that is not a faceted surface (the part's faces then come from the delivered model)"""
        if it.is_a('IfcMappedItem'):
            src = it.MappingSource
            M = T @ self.ctx.cto3(it.MappingTarget) @ self.ctx.ax3(src.MappingOrigin)     # as for parametric items
            out = []
            for sub in src.MappedRepresentation.Items:
                out += self.faceted(sub, M)
            return out
        if it.is_a('IfcFacetedBrep'):                      # includes IfcFacetedBrepWithVoids
            voids = [self.shell_faces(v.CfsFaces, T) for v in it.Voids] if it.is_a('IfcFacetedBrepWithVoids') else []
            return [{'faces': self.shell_faces(it.Outer.CfsFaces, T), 'voids': voids}]
        if it.is_a('IfcShellBasedSurfaceModel'):
            return [{'faces': self.shell_faces(s.CfsFaces, T), 'voids': []} for s in it.SbsmBoundary]
        if it.is_a('IfcFaceBasedSurfaceModel'):
            return [{'faces': self.shell_faces(s.CfsFaces, T), 'voids': []} for s in it.FbsmFaces]
        if it.is_a('IfcPolygonalFaceSet') or it.is_a('IfcTriangulatedFaceSet'):
            return [{'faces': self.face_set(it, T), 'voids': []}]
        raise Unsupported('faceted ' + it.is_a())

    def _world(self, P, T):
        """points (n x 2|3, file length units) -> model mm under T; under a mirroring T the loop is reversed so that
        faces keep facing out"""
        P = np.asarray(P, float)
        if P.ndim != 2 or len(P) == 0:
            raise Unsupported('empty loop')
        if P.shape[1] == 2:
            P = np.hstack([P, np.zeros((len(P), 1))])
        W = (P * self.ctx.L) @ T[:3, :3].T + T[:3, 3]
        return W[::-1] if np.linalg.det(T[:3, :3]) < 0 else W

    def shell_faces(self, faces, T):
        out = []
        for fc in faces:
            if not fc.is_a('IfcFace') or fc.is_a('IfcFaceSurface') or fc.is_a('IfcOrientedFace'):
                raise Unsupported('face ' + fc.is_a())
            loops, outer = [], []
            for b in fc.Bounds:
                lp = b.Bound
                if not lp.is_a('IfcPolyLoop'):
                    raise Unsupported('face bound ' + lp.is_a())
                W = self._world([p.Coordinates for p in lp.Polygon], T)
                if not b.Orientation:
                    W = W[::-1]
                if b.is_a('IfcFaceOuterBound'):
                    outer.append(len(loops))
                loops.append(W)
            if not loops:
                raise Unsupported('face without bounds')
            if len(outer) > 1:
                raise Unsupported('face with several outer bounds')
            # no IfcFaceOuterBound: the bound enclosing the largest area is the outer one
            k = outer[0] if outer else int(np.argmax([np.linalg.norm(_newell(W)) for W in loops]))
            out.append([_loop(loops[k])] + [_loop(W) for i, W in enumerate(loops) if i != k])
        return out

    def face_set(self, it, T):
        """IfcPolygonalFaceSet / IfcTriangulatedFaceSet (IFC4) -> faces"""
        C = np.asarray(it.Coordinates.CoordList, float)
        pn = [i - 1 for i in it.PnIndex] if getattr(it, 'PnIndex', None) else None
        ix = (lambda i: pn[i - 1]) if pn is not None else (lambda i: i - 1)
        out = []
        if it.is_a('IfcTriangulatedFaceSet'):
            for tri in it.CoordIndex:
                out.append([self._map(C, [ix(i) for i in tri], T)])
            return out
        for fc in it.Faces:
            f = [self._map(C, [ix(i) for i in fc.CoordIndex], T)]
            if fc.is_a('IfcIndexedPolygonalFaceWithVoids'):
                f += [self._map(C, [ix(i) for i in h], T) for h in fc.InnerCoordIndices]
            out.append(f)
        return out

    def _map(self, C, idx, T):
        return _loop(self._world(C[idx], T))


def _newell(W):
    W = np.asarray(W, float)
    q = np.roll(W, -1, axis=0)
    return np.array([np.sum((W[:, 1] - q[:, 1]) * (W[:, 2] + q[:, 2])), np.sum((W[:, 2] - q[:, 2]) * (W[:, 0] + q[:, 0])),
                     np.sum((W[:, 0] - q[:, 0]) * (W[:, 1] + q[:, 1]))])


def _loop(W):
    """model mm loop; a vertex repeating its predecessor (or the closing repeat of the first) is dropped"""
    pts = [[_r(v) for v in p] for p in W]
    pts = [q for i, q in enumerate(pts) if i == 0 or q != pts[i - 1]]
    while len(pts) > 1 and pts[-1] == pts[0]:
        pts.pop()
    return pts


FACET_FLAT_TOL = 0.01      # mm: largest distance of a face's vertices from its plane
FOLD_TOL = 1e-5            # mm: a loop vertex this close to the line through the previous edge, and turning back


def _folds_back(k):
    """a loop that runs back along itself (a zero-width spike: the edge after a vertex turns back onto the edge before
    it), which bounds no area there and leaves the face's boundary self-overlapping"""
    P = np.asarray(k, float)
    a, b, c = np.roll(P, 1, axis=0), P, np.roll(P, -1, axis=0)
    e1, e2 = b - a, c - b
    l1 = np.linalg.norm(e1, axis=1)
    off = np.linalg.norm(np.cross(e1, e2), axis=1) / np.where(l1 > 0, l1, 1.0)     # distance of c from line a-b
    return bool(np.any((off < FOLD_TOL) & (np.einsum('ij,ij->i', e1, e2) < 0)))
FACES_IFC = 'IFC faceted geometry, full precision'      # 'source' of an exact_ifc.jsonl record


def faceted_defect(solids):
    """'' when every shell of the faceted solids bounds a polyhedron without ambiguity: each face has at least three
    distinct vertices and is flat within FACET_FLAT_TOL, and the shell is closed and consistently oriented - every edge
    between two consecutive loop vertices (vertices identified by their coordinates) is used exactly once in each
    direction. Otherwise the reason. Faces that do not close up (open shells, T-junctions, overlapping or duplicate
    facets) leave the solid to interpretation; such parts keep the faces of the delivered model."""
    for so in solids:
        for shell in [so['faces']] + list(so.get('voids', [])):
            E = collections.Counter()
            for fc in shell:
                W = np.asarray(fc[0], float)
                n = _newell(W)
                ln = np.linalg.norm(n)
                if ln == 0.0:
                    return 'degenerate face'
                c = W.mean(0)
                d = np.concatenate([(np.asarray(lp, float) - c) @ (n / ln) for lp in fc])
                if d.max() - d.min() > FACET_FLAT_TOL:
                    return 'face not flat'
                for lp in fc:
                    k = [tuple(q) for q in lp]
                    k = [q for i, q in enumerate(k) if q != k[i - 1]]          # drop repeated vertices (incl. closing one)
                    if len(k) < 3:
                        return 'degenerate face'
                    if _folds_back(k):
                        return 'face loop folds back on itself'
                    for a, b in zip(k, k[1:] + k[:1]):
                        E[(a, b)] += 1
            for (a, b), m in E.items():
                if m != 1 or E.get((b, a), 0) != 1:
                    return 'shell not closed and consistently oriented'
    return ''


def _signed_volume(shell):
    """6 x the signed volume of a closed polygon shell (fan triangles per loop, about a local origin)"""
    ref = np.asarray(shell[0][0][0], float)
    v6 = 0.0
    for fc in shell:
        for lp in fc:
            P = np.asarray(lp, float) - ref
            a, b, c = P[0], P[1:-1], P[2:]
            v6 += float(np.sum(np.einsum('j,ij->i', a, np.cross(b, c))))
    return v6


def _components(shell):
    """indices of the faces of each edge-connected piece of a shell"""
    parent = list(range(len(shell)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    seen = {}
    for i, fc in enumerate(shell):
        for lp in fc:
            k = [tuple(q) for q in lp]
            for a, b in zip(k, k[1:] + k[:1]):
                e = (a, b) if a < b else (b, a)
                if e in seen:
                    ra, rb = find(i), find(seen[e])
                    if ra != rb:
                        parent[ra] = rb
                else:
                    seen[e] = i
    out = collections.defaultdict(list)
    for i in range(len(shell)):
        out[find(i)].append(i)
    return list(out.values())


def orient_outward(solids):
    """faces of every closed shell facing out of the material: an outer shell bounding a positive volume, a void shell
    a negative one (the IfcOpenShell kernel orients the shells of a faceted B-rep the same way, and so did the delivered
    model). A shell the IFC states inside out is reversed as a whole; Unsupported for a shell whose separate closed
    pieces face different ways (which pieces are cavities would be a guess). An outer shell (without voids) made of
    several separate closed pieces gives one solid per piece, as the delivered model holds them."""
    out = []
    for so in solids:
        def fix(shell, want):
            comps = _components(shell)
            sg = [np.sign(_signed_volume([shell[i] for i in c])) for c in comps]
            if any(x == 0 for x in sg) or len(set(sg)) > 1:
                raise Unsupported('shell pieces oriented both ways')
            return (shell if sg[0] == want else [[lp[::-1] for lp in fc] for fc in shell]), comps
        faces, comps = fix(so['faces'], 1.0)
        voids = [fix(v, -1.0)[0] for v in so.get('voids', [])]
        if voids or len(comps) == 1:
            out.append({'faces': faces, 'voids': voids})
        else:
            for c in sorted(comps, key=min):
                out.append({'faces': [faces[i] for i in sorted(c)], 'voids': []})
    return out


def psets(elem):
    out = {}
    for rel in getattr(elem, 'IsDefinedBy', None) or []:
        if rel.is_a('IfcRelDefinesByProperties'):
            pd = rel.RelatingPropertyDefinition
            if pd.is_a('IfcPropertySet'):
                for pr in pd.HasProperties:
                    if pr.is_a('IfcPropertySingleValue') and pr.NominalValue is not None:
                        out[pd.Name + '.' + pr.Name] = pr.NominalValue.wrappedValue
    return out


def material_of(elem):
    for rel in getattr(elem, 'HasAssociations', None) or []:
        if rel.is_a('IfcRelAssociatesMaterial'):
            m = rel.RelatingMaterial
            if m.is_a('IfcMaterial'):
                return m.Name
            if m.is_a('IfcMaterialLayerSetUsage'):
                return '; '.join(l.Material.Name for l in m.ForLayerSet.MaterialLayers if l.Material)
            if m.is_a('IfcMaterialLayerSet'):
                return '; '.join(l.Material.Name for l in m.MaterialLayers if l.Material)
            if m.is_a('IfcMaterialList'):
                return '; '.join(x.Name for x in m.Materials)
            if m.is_a('IfcMaterialProfileSetUsage') or m.is_a('IfcMaterialProfileSet'):
                ps = m.ForProfileSet if m.is_a('IfcMaterialProfileSetUsage') else m
                return '; '.join(p.Material.Name for p in ps.MaterialProfiles if p.Material)
    return ''


def role_of(p, ps):
    c = p.is_a()
    n = (p.Name or '').lower()
    if c in ('IfcMechanicalFastener',) or (c == 'IfcFastener' and 'bolt' in n):
        return 'bolt'
    if c == 'IfcFastener' or 'weld' in n:
        return 'weld'
    if c in ('IfcFooting', 'IfcSlab', 'IfcWall', 'IfcWallStandardCase', 'IfcPile') or 'concrete' in (material_of(p) or '').lower():
        return 'concrete'
    if c == 'IfcPlate' or 'plate' in n or re.match(r'^(PL|FL|BPL|BP)\b', (p.ObjectType or p.Description or '').upper()):
        return 'plate'
    if c in ('IfcBeam', 'IfcColumn', 'IfcMember'):
        return 'member'
    if c == 'IfcDiscreteAccessory':
        return 'accessory'
    return 'other'


def assembly_own_mark(assembly, aps=None):
    """the mark an assembly carries itself (its property sets, else its Tag); '' when it carries none"""
    aps = psets(assembly) if aps is None else aps
    return (aps.get('AISC_EM11_Pset_AssemblyIdentification.AssemblyMark') or aps.get('Tekla Assembly.Assembly/Cast unit Mark')
            or (assembly.Tag if assembly.Tag and assembly.Tag != '0' else '') or '')


def marks_of(p, ps, assembly):
    piece = ps.get('AISC_EM11_Pset_PieceIdentification.PieceMark') or ps.get('Tekla Common.Part mark') or ''
    ind = ps.get('AISC_EM11_Pset_PieceIdentification.IndicationMark') or ''
    tag = p.Tag or ''
    if re.match(r'^ID[0-9a-f-]{20,}$', tag) or re.match(r'^\d{5,}$', tag) or tag == '0':
        tag = ''                                    # GUID-like / element-id tags are not piece marks
    part_mark = ind or piece or tag
    asm = ''
    if assembly is not None:
        asm = assembly_own_mark(assembly)
    asm = asm or ps.get('Tekla Assembly.Assembly/Cast unit Mark', '') or ps.get('AISC_EM11_Pset_AssemblyIdentification.AssemblyMark', '')
    dwg = ps.get('AISC_EM11_Pset_DrawingNumber.DrawingNumber', '')
    if assembly is not None and not dwg:
        dwg = psets(assembly).get('AISC_EM11_Pset_DrawingNumber.DrawingNumber', '')
    return str(part_mark), str(asm), str(dwg)


def assembly_tree(f):
    """every IfcElementAssembly of the model (file order) with its parent assembly (IfcRelAggregates; '' at the top) and
    its depth (0 = top level), so that an assembly whose members are only other assemblies is listed too"""
    parent = {}
    for rel in f.by_type('IfcRelAggregates'):
        if rel.RelatingObject.is_a('IfcElementAssembly'):
            for o in rel.RelatedObjects:
                if o.is_a('IfcElementAssembly'):
                    parent[o.GlobalId] = rel.RelatingObject.GlobalId
    def depth(g):
        d, seen = 0, {g}
        while g in parent and parent[g] not in seen:          # a cyclic aggregation (invalid IFC) stops the walk
            g = parent[g]
            seen.add(g)
            d += 1
        return d
    rows = []
    for a in f.by_type('IfcElementAssembly'):
        aps = psets(a)
        rows.append(dict(assembly_id=a.GlobalId, parent_id=parent.get(a.GlobalId, ''), depth=depth(a.GlobalId),
                         assembly_mark=str(assembly_own_mark(a, aps)), name=a.Name or '',
                         drawing_ref=str(aps.get('AISC_EM11_Pset_DrawingNumber.DrawingNumber', '') or '')))
    return rows


def designation_of(p, ps):
    for k in ('Pset_BeamCommon.Reference', 'Pset_ColumnCommon.Reference', 'Pset_MemberCommon.Reference', 'Pset_PlateCommon.Reference'):
        if ps.get(k):
            return str(ps[k])
    return p.ObjectType or p.Description or ''


def extract(ifc_path, out_dir, only=None):
    f = open_ifc(ifc_path)
    M = Model(f)
    os.makedirs(out_dir, exist_ok=True)
    assembly_of = {}
    for rel in f.by_type('IfcRelAggregates'):
        if rel.RelatingObject.is_a('IfcElementAssembly'):
            for o in rel.RelatedObjects:
                assembly_of[o.id()] = rel.RelatingObject
    voids = collections.defaultdict(list)
    for rel in f.by_type('IfcRelVoidsElement'):
        voids[rel.RelatingBuildingElement.id()].append(rel.RelatedOpeningElement)
    parts = []
    status = collections.Counter()
    faceted, faceted_not = {}, collections.Counter()
    # an IFC our SDS/2 converter's emitter wrote (z3-sds2-ifc-emitter): its parts are read by Model.sds2_part; every other
    # IFC is read exactly as before
    sds2 = str(f.header.file_name.originating_system).startswith(SDS2_EMITTER)
    for p in f.by_type('IfcProduct'):
        if any(p.is_a(c) for c in SKIP_CLASSES) or not p.Representation or p.is_a('IfcElementAssembly'):
            continue
        reps = [r for r in p.Representation.Representations if r.RepresentationIdentifier in BODY_IDS and r.Items]
        if not reps:
            continue
        if only and p.GlobalId not in only:
            continue
        ps = psets(p)
        asm = assembly_of.get(p.id())
        pmark, amark, dwg = marks_of(p, ps, asm)
        row = dict(part_id=p.GlobalId, ifc_class=p.is_a(), role=role_of(p, ps), name=p.Name or '', designation=designation_of(p, ps),
                   material=material_of(p), part_mark=pmark, assembly_mark=amark, drawing_ref=dwg,
                   assembly_id=asm.GlobalId if asm is not None else '', geometry='parametric', note='')
        n_solids, n_cuts, n_sol0, n_open0, n_bounds0 = len(M.solids), len(M.cuts), len(M.solids), len(M.openings), set(M.bounds)
        if sds2:
            try:
                T = M.ctx.placement(p.ObjectPlacement)
                sol = M.sds2_part(p.GlobalId, reps[0], T)       # the converter uses the first body representation
                if sol:
                    why = faceted_defect(sol)
                    if why:
                        raise Unsupported(why)
                    faceted[p.GlobalId] = orient_outward(sol)
                    row['geometry'] = 'exact'
                    row['note'] = 'SDS/2 faceted piece' + (' with hole tools' if len(M.openings) > n_open0 else '') +                                   (' and extrusions' if len(M.solids) > n_sol0 + sum(len(o['tool_solids'].split()) for o in M.openings[n_open0:]) else '')
                    status['exact:sds2 faceted' + (' + holes' if len(M.openings) > n_open0 else '')] += 1
                else:
                    status['parametric'] += 1
            except Unsupported as e:
                del M.solids[n_sol0:]
                del M.cuts[n_cuts:]
                del M.openings[n_open0:]
                for k in set(M.bounds) - n_bounds0:
                    del M.bounds[k]
                faceted.pop(p.GlobalId, None)
                row['geometry'] = 'exact'
                row['note'] = 'SDS/2 item not read: ' + str(e)
                status['exact:sds2 unread'] += 1
                faceted_not['sds2: ' + str(e)] += 1
            parts.append(row)
            continue
        try:
            T = M.ctx.placement(p.ObjectPlacement)
            for r in reps[:1]:                 # the converter uses the first body representation
                for it in r.Items:
                    M.item(p.GlobalId, 'body', it, T)
            for op in voids.get(p.id(), []):
                if not op.Representation:
                    continue
                To = M.ctx.placement(op.ObjectPlacement)
                oid = f'O{len(M.openings) + 1}'
                tools = []
                for r in op.Representation.Representations:
                    if r.RepresentationIdentifier in BODY_IDS:
                        for it in r.Items:
                            tools += M.item(p.GlobalId, 'opening_tool', it, To, opening_id=oid)
                M.openings.append(dict(opening_id=oid, part_id=p.GlobalId, opening_guid=op.GlobalId, tool_solids=' '.join(tools)))
            status['parametric'] += 1
        except Unsupported as e:
            # roll back this part's partial rows; its geometry comes from exact_geometry.jsonl
            del M.solids[n_sol0:]
            del M.cuts[n_cuts:]
            del M.openings[n_open0:]
            for k in set(M.bounds) - n_bounds0:
                del M.bounds[k]
            row['geometry'] = 'exact'
            row['note'] = str(e)
            status['exact:' + str(e).split(' ')[0] + ' ' + (str(e).split(' ')[1] if ' ' in str(e) else '')] += 1
            # its faces, read from the IFC at full precision when the source states the part as faceted surfaces
            # (exact.py takes them from the delivered model, whose coordinates sit on a 0.01 mm grid, otherwise)
            try:
                if any(op.Representation for op in voids.get(p.id(), [])):
                    raise Unsupported('openings subtracted from faceted surfaces')
                T = M.ctx.placement(p.ObjectPlacement)
                sol = []
                for it in reps[0].Items:          # the converter uses the first body representation
                    sol += M.faceted(it, T)
                if not sol:
                    raise Unsupported('no faceted solid')
                why = faceted_defect(sol)
                if why:
                    raise Unsupported(why)
                faceted[p.GlobalId] = orient_outward(sol)
            except Unsupported as e2:
                faceted_not[str(e2)] += 1
            except Exception as e2:               # this route never stops the extraction: the delivered faces stand
                faceted_not['error ' + type(e2).__name__] += 1
        parts.append(row)

    def wcsv(name, rows, cols):
        with open(os.path.join(out_dir, name), 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
            w.writeheader()
            for r in rows:
                w.writerow(r)
    wcsv('parts.csv', parts, ['part_id', 'ifc_class', 'role', 'name', 'designation', 'material', 'part_mark', 'assembly_mark',
                              'drawing_ref', 'assembly_id', 'geometry', 'note'])
    pcols = ['profile_id', 'kind', 'designation', 'd', 'b', 'tw', 'tf', 't', 'r', 'r_edge', 'r_inner', 'r_outer', 'slope', 'radius',
             'pos_x', 'pos_y', 'pos_angle', 'sides', 'radius_inner', 'angle_inner']
    wcsv('profiles.csv', M.prof.rows, pcols)
    json.dump(M.prof.outlines, open(os.path.join(out_dir, 'profile_outlines.json'), 'w'), separators=(',', ':'))
    wcsv('solids.csv', M.solids, ['solid_id', 'part_id', 'role', 'opening_id', 'profile_id', 'ox', 'oy', 'oz', 'xx', 'xy', 'xz',
                                  'zx', 'zy', 'zz', 'vx', 'vy', 'vz', 'scale', 'fxx', 'fxy', 'fxz', 'fzx', 'fzy', 'fzz'])
    wcsv('cuts.csv', M.cuts, ['cut_id', 'solid_id', 'kind', 'px', 'py', 'pz', 'nx', 'ny', 'nz', 'tool_solid_id'])
    json.dump(M.bounds, open(os.path.join(out_dir, 'cut_boundaries.json'), 'w'), separators=(',', ':'))
    wcsv('openings.csv', M.openings, ['opening_id', 'part_id', 'opening_guid', 'tool_solids'])
    with open(os.path.join(out_dir, 'exact_ifc.jsonl'), 'w') as fh:
        for r in parts:
            if r['part_id'] in faceted:
                fh.write(json.dumps({'part_id': r['part_id'], 'source': FACES_IFC, 'solids': faceted[r['part_id']]},
                                    separators=(',', ':')) + '\n')
    tree = assembly_tree(f)
    wcsv('assembly_tree.csv', tree, ['assembly_id', 'parent_id', 'depth', 'assembly_mark', 'name', 'drawing_ref'])
    info = dict(source=os.path.basename(ifc_path), schema=f.schema, length_unit_to_mm=M.ctx.L, angle_unit_to_rad=M.ctx.A,
                originating_system=str(f.header.file_name.originating_system), parts=len(parts), status=dict(status),
                profiles=len(M.prof.rows), solids=len(M.solids), cuts=len(M.cuts), openings=len(M.openings),
                assemblies=len(tree), nested_assemblies=sum(1 for t in tree if t['parent_id']),
                exact_faces=dict(from_ifc=len(faceted), not_from_ifc=dict(sorted(faceted_not.items()))))
    json.dump(info, open(os.path.join(out_dir, 'extract_info.json'), 'w'), indent=1)
    return info


def write_assembly_tree(ifc_path, out_dir):
    """assembly_tree.csv alone (for schedules extracted before it existed); the rows are those extract() writes"""
    tree = assembly_tree(open_ifc(ifc_path))
    with open(os.path.join(out_dir, 'assembly_tree.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['assembly_id', 'parent_id', 'depth', 'assembly_mark', 'name', 'drawing_ref'])
        w.writeheader()
        w.writerows(tree)
    return len(tree)


if __name__ == '__main__':
    if len(sys.argv) > 3 and sys.argv[3] == '--assembly-tree-only':
        print(write_assembly_tree(sys.argv[1], sys.argv[2]), 'assemblies')
    else:
        print(json.dumps(extract(sys.argv[1], sys.argv[2]), indent=1))
