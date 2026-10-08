"""steelbuild - construct a structural steel model from its schedules with build123d.

The schedules (CSV/JSON, millimetres, model coordinates) describe every part of a model:

  parts.csv            part list: id, IFC class, role, name, marks, profile designation, material, geometry kind
  profiles.csv         cross-sections: I, U, L, T, RECT, RHS, CIRCLE, CHS with their dimensions; POLY (outline file)
  profile_outlines.json  POLY outlines as line runs, three-point arcs and elliptical arcs
  solids.csv           extruded solids: profile, profile plane (origin, x axis, normal), extrusion vector
  cuts.csv             cuts applied to a solid: plane, polygon-bounded plane, or a cutting solid
  cut_boundaries.json  polygons bounding the bounded plane cuts
  openings.csv         openings (holes, copes, notches) cut from a whole part by opening solids
  paths.json           (optional) swept solids: the polyline path a solid's section follows instead of one straight vector
  exact_geometry.jsonl parts the source defines only as faceted surfaces: their exact polygon faces

Every parametric part is constructed as: profile -> placed on its plane -> extruded along its vector (or swept along
its path) -> cut by its cuts -> openings subtracted. Parts without parameters are built from their exact faces.
Nothing else is assumed.

paths.json maps a solid_id of solids.csv to the path its section is swept along (mm, model coordinates):

  {"S123": {"points": [[x, y, z], ...],      the section's reference point (profile origin) at every path vertex
            "closed": false,                 true: the last point joins the first again (a ring, e.g. a weld all round)
            "section": "perpendicular",      where the profile sits on each straight segment (see below)
            "normals": [null, "in", [nx, ny, nz], ...],    optional, one entry per point: the joint plane there
            "scales": [1.0, 1.0, 2.0, ...]}}             optional (section "joint"), one per point: profile scale there

Each straight segment of the path is the profile extruded along that segment, trimmed by the joint planes at its two
ends; the trimmed segments are fused into one solid. The joint plane at a point passes through it; its normal is
  null (default)   interior point: the bisector of the two segments (a mitre); end point: square to the end segment
  "in" / "out"     square to the incoming / outgoing segment
  [nx, ny, nz]     that normal (oblique ends, joints the source cuts at another angle)
"section" says where the profile sits:
  "perpendicular"  square to every segment (a classic sweep: the cross-section is the profile all along the path, the
                   mitre joints show it stretched)
  "joint"          on every segment's start joint plane (how faceted bends are stored: the profile itself is found on
                   every joint plane and each segment between two joint planes is straight)
The profile's frame on the first point is that solid's row in solids.csv: origin ox oy oz = the first point, section x
axis xx xy xz; zx zy zz repeats the first section plane normal (the build takes it from the path) and vx vy vz the
first segment. Along the path the section x axis is carried by the smallest rotation from one section plane normal to
the next (no twist). "scales" (only with section "joint") scales the profile about its origin at every point; a
segment whose two scales differ is the ruled solid joining its two end sections corner to corner (a frustum: a cone
between a bolt shank and its head); two consecutive equal points with different scales are a step (a shoulder where
the section changes size in place). Cuts in cuts.csv and the part's openings apply to the swept solid as to any other
solid. A solid without an entry in paths.json is a straight extrusion, exactly as before.

A solid of role cut_tool (solids.csv) is not part of the model by itself: a cuts.csv row of kind 'solid' names it in
tool_solid_id and subtracts it from the solid in solid_id (a cope, a notch, a hole, the ring around a stud's shank);
a tool is built like any other solid, with its own cuts (which may again be tools).

Requires: build123d (pip install build123d).
"""
from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass

from build123d import (Edge, Face, Wire, Shell, Solid, Compound, Vector, Plane, Location, Axis, Keep, split,
                       export_step, Shape, Part)
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid
from OCP.ShapeFix import ShapeFix_Solid
from OCP.TopAbs import TopAbs_SHELL
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Vec, gp_Pnt, gp_Dir, gp_Pln
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Copy
from OCP.ShapeFix import ShapeFix_Face, ShapeFix_Shell, ShapeFix_ShapeTolerance
from OCP.TopAbs import TopAbs_VERTEX, TopAbs_EDGE

TOL = 1e-6          # mm, coincident points
# The IfcOpenShell kernel gives every shape it builds its precision (1e-5 m = 0.01 mm) as B-rep tolerance on the profile's
# vertices and edges (the swept solid's lateral faces and edges inherit it; the two caps keep 1e-7). OpenCASCADE booleans
# treat entities closer than the operands' tolerances as coincident, so a sliver thinner than ~0.01 mm left between a body
# face and a nearly coincident cut / opening face is merged away in the source; the rebuild carries the same tolerance.
KERNEL_TOL = 0.01   # mm


# ======================================================================================== schedules
def _num(v, default=0.0):
    return default if v in (None, '') else float(v)


@dataclass
class Schedules:
    folder: str

    def __post_init__(self):
        f = lambda n: os.path.join(self.folder, n)
        rd = lambda n: list(csv.DictReader(open(f(n), newline='', encoding='utf-8'))) if os.path.exists(f(n)) else []
        self.parts = rd('parts.csv')
        self.profiles = {r['profile_id']: r for r in rd('profiles.csv')}
        self.outlines = json.load(open(f('profile_outlines.json'))) if os.path.exists(f('profile_outlines.json')) else {}
        self.solids = {r['solid_id']: r for r in rd('solids.csv')}
        self.cuts = rd('cuts.csv')
        self.boundaries = json.load(open(f('cut_boundaries.json'))) if os.path.exists(f('cut_boundaries.json')) else {}
        self.openings = rd('openings.csv')
        self.paths = json.load(open(f('paths.json'))) if os.path.exists(f('paths.json')) else {}
        self.exact = {}
        if os.path.exists(f('exact_geometry.jsonl')):
            for line in open(f('exact_geometry.jsonl')):
                if line.strip():
                    r = json.loads(line)
                    self.exact[r['part_id']] = r
        self.body_of, self.cuts_of, self.open_of = {}, {}, {}
        for s in self.solids.values():
            if s['role'] == 'body':
                self.body_of.setdefault(s['part_id'], []).append(s['solid_id'])
        for c in self.cuts:
            self.cuts_of.setdefault(c['solid_id'], []).append(c)
        for o in self.openings:
            self.open_of.setdefault(o['part_id'], []).append(o)


# ======================================================================================== 2D profiles
def _v(x, y):
    return Vector(float(x), float(y), 0.0)


def _rounded_polygon(pts, radii):
    """closed polygon (list of (x, y)); radii[i] > 0 rounds corner i with a tangent arc (convex or concave).
    A rounding that does not fit (tangent point beyond an adjacent edge, e.g. an edge radius larger than the flange
    thickness) becomes a straight chamfer between the points at the same distance from the corner measured along the
    outline - as the IfcOpenShell kernel resolves it."""
    n = len(pts)
    P = [Vector(x, y, 0) for x, y in pts]
    seglen = [(P[(i + 1) % n] - P[i]).length for i in range(n)]

    def walk(i, d, step):
        """point at boundary distance d from vertex i going forward (step=+1) or backward (-1); vertices passed"""
        j, passed = i, []
        while True:
            k = (j + step) % n
            L = seglen[j] if step > 0 else seglen[k]
            if d <= L + 1e-9:
                return P[j] + (P[k] - P[j]).normalized() * d, passed
            d -= L
            j = k
            passed.append(j)

    corners = {}
    removed = set()
    for i in range(n):
        r = radii[i]
        if not r or i in removed:
            continue
        a, b, c = P[i - 1], P[i], P[(i + 1) % n]
        u1, u2 = (a - b).normalized(), (c - b).normalized()
        cosang = max(-1.0, min(1.0, u1.dot(u2)))
        half = math.acos(cosang) / 2.0
        d = r / math.tan(half)
        if d <= seglen[i - 1] + 1e-9 and d <= seglen[i] + 1e-9:
            t1, t2 = b + u1 * d, b + u2 * d
            ctr = b + (u1 + u2).normalized() * (r / math.sin(half))
            mid = ctr + (b - ctr).normalized() * r
            corners[i] = ('arc', t1, mid, t2)
        else:
            t1, back = walk(i, d, -1)
            t2, fwd = walk(i, d, +1)
            removed.update(back + fwd)
            corners[i] = ('chamfer', t1, t2)
    order = [i for i in range(n) if i not in removed]
    seq = []                                       # (start point, end point, kind, mid) in outline order
    pts_out = []
    for i in order:
        cn = corners.get(i)
        if cn is None:
            pts_out.append(('v', P[i]))
        elif cn[0] == 'arc':
            pts_out.append(('arc', cn[1], cn[2], cn[3]))
        else:
            pts_out.append(('cham', cn[1], cn[2]))
    edges = []
    def first_pt(e):
        return e[1]
    def last_pt(e):
        return e[1] if e[0] == 'v' else e[-1]
    for k, e in enumerate(pts_out):
        if e[0] == 'arc':
            edges.append(Edge.make_three_point_arc(e[1], e[2], e[3]))
        elif e[0] == 'cham' and (e[2] - e[1]).length > TOL:
            edges.append(Edge.make_line(e[1], e[2]))
        nxt = pts_out[(k + 1) % len(pts_out)]
        s_, t_ = last_pt(e), first_pt(nxt)
        if (t_ - s_).length > TOL:
            edges.append(Edge.make_line(s_, t_))
    return Wire(edges)


def _ellipse_edges(s):
    """elliptical arc segment {"t": "E", "p": [start, mid, end], "c": centre, "x": unit direction of the first semi-axis,
    "r": [first semi-axis, second semi-axis]} -> edges from start through mid to end (the arc lies on the ellipse
    P(t) = c + r1 cos(t) x + r2 sin(t) y; start / end are joined to it by lines should they sit off it)"""
    from OCP.gp import gp_Ax2, gp_Elips
    from OCP.Geom import Geom_Ellipse, Geom_TrimmedCurve
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    (cx, cy), (ux, uy), (r1, r2) = [float(v) for v in s['c']], [float(v) for v in s['x']], [float(v) for v in s['r']]
    n = math.hypot(ux, uy)
    ux, uy = ux / n, uy / n
    if r2 > r1:                    # OpenCASCADE wants the major axis first: x' = y, y' = -x
        X, a, b = (-uy, ux), r2, r1
    else:
        X, a, b = (ux, uy), r1, r2
    Y = (-X[1], X[0])
    el = gp_Elips(gp_Ax2(gp_Pnt(cx, cy, 0.0), gp_Dir(0.0, 0.0, 1.0), gp_Dir(X[0], X[1], 0.0)), a, b)
    par = lambda q: math.atan2(((q[0] - cx) * Y[0] + (q[1] - cy) * Y[1]) / b, ((q[0] - cx) * X[0] + (q[1] - cy) * X[1]) / a)
    p = [[float(v) for v in q] for q in s['p']]
    t0, tm, t1 = par(p[0]), par(p[1]), par(p[2])
    two = 2.0 * math.pi
    ccw = (tm - t0) % two < (t1 - t0) % two
    if ccw:
        u0, u1 = t0, t0 + ((t1 - t0) % two or two)
    else:
        u0, u1 = t1, t1 + ((t0 - t1) % two or two)
    ge = Geom_Ellipse(el)
    e = BRepBuilderAPI_MakeEdge(Geom_TrimmedCurve(ge, u0, u1)).Edge()
    arc = Edge(e) if ccw else Edge(e.Reversed())
    edges = []
    v = lambda u: Vector(ge.Value(u).X(), ge.Value(u).Y(), 0.0)
    a0, a1 = (v(u0), v(u1)) if ccw else (v(u1), v(u0))          # the arc's own start and end, in the segment's direction
    if (a0 - _v(*p[0])).length > TOL:
        edges.append(Edge.make_line(_v(*p[0]), a0))
    edges.append(arc)
    if (a1 - _v(*p[2])).length > TOL:
        edges.append(Edge.make_line(a1, _v(*p[2])))
    return edges


def _segments_wire(segs):
    edges = []
    for s in segs:
        p = [_v(*q) for q in s['p']]
        if s['t'] == 'L':
            for a, b in zip(p, p[1:]):
                if (b - a).length > TOL:
                    edges.append(Edge.make_line(a, b))
        elif s['t'] == 'E':
            edges += _ellipse_edges(s)
        else:
            edges.append(Edge.make_three_point_arc(p[0], p[1], p[2]))
    return Wire(edges)


def profile_face(row: dict, outline: dict | None = None) -> Face:
    """cross-section as a planar face in the XY plane (profile coordinates, mm)"""
    k = row['kind']
    g = lambda c: _num(row.get(c))
    if k == 'I':
        B, D, tw, tf, r = g('b'), g('d'), g('tw'), g('tf'), g('r')
        x, y, w = B / 2, D / 2, tw / 2
        pts = [(-x, -y), (x, -y), (x, -y + tf), (w, -y + tf), (w, y - tf), (x, y - tf), (x, y), (-x, y), (-x, y - tf),
               (-w, y - tf), (-w, -y + tf), (-x, -y + tf)]
        rad = [0, 0, 0, r, r, 0, 0, 0, 0, r, r, 0]
        face = Face(_rounded_polygon(pts, rad))
    elif k == 'U':
        D, B, tw, tf, r, re_, sl = g('d'), g('b'), g('tw'), g('tf'), g('r'), g('r_edge'), g('slope')
        x, y = B / 2, D / 2
        # sloped flanges (IFC FlangeSlope): the inner flange face has thickness tf on the section's centre line x = 0
        # and tapers by tan(slope) per unit x towards the toes (as the IfcOpenShell kernel builds it)
        k = math.tan(sl) if sl else 0.0
        yin = lambda xx: -y + tf - xx * k
        pts = [(-x, -y), (x, -y), (x, yin(x)), (-x + tw, yin(-x + tw)), (-x + tw, -yin(-x + tw)), (x, -yin(x)),
               (x, y), (-x, y)]
        rad = [0, 0, re_, r, r, re_, 0, 0]
        face = Face(_rounded_polygon(pts, rad))
    elif k == 'L':
        D, B, t, r, re_, sl = g('d'), g('b'), g('t'), g('r'), g('r_edge'), g('slope')
        x, y = B / 2, D / 2
        if sl:
            raise ValueError('L profile with leg slope')
        pts = [(-x, -y), (x, -y), (x, -y + t), (-x + t, -y + t), (-x + t, y), (-x, y)]
        rad = [0, 0, re_, r, re_, 0]
        face = Face(_rounded_polygon(pts, rad))
    elif k == 'T':
        # flange on top (y = D/2 - tf .. D/2), web of thickness tw centred on x = 0 down to y = -D/2; r = root fillets
        # between web and flange, r_edge = rounded underside corners of the flange toes (IfcTShapeProfileDef as the
        # IfcOpenShell kernel builds it)
        D, B, tw, tf, r, re_ = g('d'), g('b'), g('tw'), g('tf'), g('r'), g('r_edge')
        x, y, w = B / 2, D / 2, tw / 2
        pts = [(-w, -y), (w, -y), (w, y - tf), (x, y - tf), (x, y), (-x, y), (-x, y - tf), (-w, y - tf)]
        rad = [0, 0, r, re_, 0, 0, re_, r]
        face = Face(_rounded_polygon(pts, rad))
    elif k == 'RECT':
        B, D, ro = g('b'), g('d'), g('r_outer')
        pts = [(-B / 2, -D / 2), (B / 2, -D / 2), (B / 2, D / 2), (-B / 2, D / 2)]
        face = Face(_rounded_polygon(pts, [ro] * 4))
    elif k == 'RHS':
        B, D, t, ri, ro = g('b'), g('d'), g('t'), g('r_inner'), g('r_outer')
        outer = _rounded_polygon([(-B / 2, -D / 2), (B / 2, -D / 2), (B / 2, D / 2), (-B / 2, D / 2)], [ro] * 4)
        bi, di = B / 2 - t, D / 2 - t
        inner = _rounded_polygon([(-bi, -di), (bi, -di), (bi, di), (-bi, di)], [ri] * 4)
        face = Face(outer, [inner])
    elif k == 'CIRCLE':
        face = Face(Wire([Edge.make_circle(g('radius'))]))
    elif k == 'CHS':
        R, t = g('radius'), g('t')
        face = Face(Wire([Edge.make_circle(R)]), [Wire([Edge.make_circle(R - t)])])
    elif k == 'NGON':
        # regular polygon of `sides` vertices on a circle of `radius` (faceted round section as the source stores it),
        # first vertex at pos_angle; optional concentric regular hole (`radius_inner`, rotated by `angle_inner`)
        n, R = int(g('sides')), g('radius')
        ring = lambda rad, a0: [(rad * math.cos(a0 + 2 * math.pi * i / n), rad * math.sin(a0 + 2 * math.pi * i / n)) for i in range(n)]
        outer = Wire.make_polygon([Vector(x, y, 0) for x, y in ring(R, 0.0)], close=True)
        inner = []
        if g('radius_inner'):
            inner = [Wire.make_polygon([Vector(x, y, 0) for x, y in ring(g('radius_inner'), g('angle_inner'))], close=True)]
        face = Face(outer, inner)
    elif k == 'POLY':
        outer = _segments_wire(outline['outer'])
        inner = [_segments_wire(s) for s in outline.get('inner', [])]
        face = Face(outer, inner)
    else:
        raise ValueError('profile kind ' + k)
    ang, px, py = g('pos_angle'), g('pos_x'), g('pos_y')
    if ang or px or py:
        face = face.moved(Location((px, py, 0), (0, 0, 1), math.degrees(ang)))
    return face


# ======================================================================================== 3D construction
def _with_kernel_tol(face):
    """independent copy of a placed profile face whose vertices and edges carry the kernel tolerance"""
    f = BRepBuilderAPI_Copy(face.wrapped).Shape()
    fix = ShapeFix_ShapeTolerance()
    fix.SetTolerance(f, KERNEL_TOL, TopAbs_VERTEX)
    fix.SetTolerance(f, KERNEL_TOL, TopAbs_EDGE)
    return f


def _plane(o, x, z):
    return Plane(origin=Vector(*o), x_dir=Vector(*x), z_dir=Vector(*z))


def _profile(sched: Schedules, pid: str) -> Face:
    """the cross-section of profile `pid`, built once per schedule object (kept on that object, so a cached face never
    outlives or crosses the schedules it came from)"""
    cache = sched.__dict__.setdefault('_faces', {})
    if pid not in cache:
        cache[pid] = profile_face(sched.profiles[pid], sched.outlines.get(pid))
    return cache[pid]


def extrude_solid(s: dict, sched: Schedules, off=(0.0, 0.0, 0.0)) -> Solid:
    """one row of solids.csv -> extruded solid, in model coordinates shifted by -off (the part's local origin)"""
    face = _profile(sched, s['profile_id'])
    sc = _num(s.get('scale'), 1.0)
    if abs(sc - 1.0) > 1e-12:
        face = face.scale(sc)
    pl = _plane((_num(s['ox']) - off[0], _num(s['oy']) - off[1], _num(s['oz']) - off[2]), (_num(s['xx']), _num(s['xy']), _num(s['xz'])),
                (_num(s['zx']), _num(s['zy']), _num(s['zz'])))
    placed = face.moved(Location(pl))
    vec = gp_Vec(_num(s['vx']), _num(s['vy']), _num(s['vz']))
    return Solid(BRepPrimAPI_MakePrism(_with_kernel_tol(placed), vec).Shape())


FUZZY = 1e-3        # mm: faces closer than this are treated as coincident in cuts (as the IfcOpenShell kernel does)


def _shape_list():
    try:
        from OCP.collections import List_TopoDS_Shape          # OCP >= 7.8 (build123d >= 0.10)
        return List_TopoDS_Shape()
    except ImportError:
        from OCP.TopTools import TopTools_ListOfShape
        return TopTools_ListOfShape()


def _volume(shape):
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    return g.Mass()


def _boxes_overlap(a, b):
    p, q = a.bounding_box(), b.bounding_box()
    return (min(p.max.X, q.max.X) - max(p.min.X, q.min.X) > KERNEL_TOL and min(p.max.Y, q.max.Y) - max(p.min.Y, q.min.Y) > KERNEL_TOL
            and min(p.max.Z, q.max.Z) - max(p.min.Z, q.min.Z) > KERNEL_TOL)


def _boolean_cut(a, b, fuzzy):
    op = BRepAlgoAPI_Cut()
    args, tools = _shape_list(), _shape_list()
    args.Append(a)
    tools.Append(b)
    op.SetArguments(args)
    op.SetTools(tools)
    op.SetFuzzyValue(fuzzy)
    op.SetNonDestructive(True)      # never modify the operands (their sub-shapes are shared with other solids)
    op.Build()
    return op.Shape() if op.IsDone() else None


def _exact_tol(shape):
    """copy of a shape with OpenCASCADE's default 1e-7 mm tolerance on every sub-shape"""
    c = BRepBuilderAPI_Copy(shape, True, False).Shape()
    ShapeFix_ShapeTolerance().SetTolerance(c, 1e-7)
    return c


def _cut(a, b):
    res = _boolean_cut(a.wrapped, b.wrapped, FUZZY)
    # a subtraction that adds volume, removes more than the tool's volume, or removes none although the tool reaches
    # into the solid's box, may have failed (e.g. a tool face crossing a nearly coincident body face within the kernel
    # tolerance): redo it with exact operand tolerances and take that result if it removes material, at most the tool's
    va, vb = _volume(a.wrapped), _volume(b.wrapped)
    vr = _volume(res) if res is not None else float('inf')
    if res is None or vr > va * (1 + 1e-9) or va - vr > vb * (1 + 1e-6) or (vr >= va * (1 - 1e-9) and _boxes_overlap(a, b)):
        r2 = _boolean_cut(_exact_tol(a.wrapped), _exact_tol(b.wrapped), FUZZY)
        if r2 is not None:
            v2 = _volume(r2)
            if va * (1 - 1e-9) > v2 >= va - vb * (1 + 1e-6):
                res = r2
    if res is None:
        raise RuntimeError('boolean cut failed')
    out = Solid(res) if res.ShapeType().name == 'TopAbs_SOLID' else Compound(res)
    sols = out.solids()
    if len(sols) == 1:
        return sols[0]
    return Compound(children=list(sols)) if sols else out


def _keep_side(shape, point, normal):
    """keep the part of `shape` on the side `normal` points to (the cut removes the other side)"""
    pl = Plane(origin=Vector(*point), z_dir=Vector(*normal))
    pieces = list(shape.split(pl, Keep.ALL))
    v0 = _volume(shape.wrapped)
    if abs(sum(_volume(p.wrapped) for p in pieces) - v0) > 1e-6 * abs(v0):
        # the splitter lost material (a plane crossing a face within the kernel tolerance): split with exact tolerances
        pieces = list(Shape.cast(_exact_tol(shape.wrapped)).split(pl, Keep.ALL))
    return Part(Compound([p for p in pieces if pl.to_local_coords(p).center().Z >= 0]).wrapped)   # as split(Keep.TOP)


# ======================================================================================== swept solids (paths.json)
def _unit(v: Vector) -> Vector:
    n = v.length
    if n < 1e-12:
        raise ValueError('sweep path: zero-length segment')
    return v * (1.0 / n)


def _carry(x: Vector, a: Vector, b: Vector) -> Vector:
    """x turned by the smallest rotation that takes unit direction a to unit direction b (the section is not twisted)"""
    k = a.cross(b)
    s, c = k.length, a.dot(b)
    if s < 1e-12:
        if c > 0:
            return x
        raise ValueError('sweep path turns back on itself')
    k = k * (1.0 / s)
    return x * c + k.cross(x) * s + k * (k.dot(x) * (1.0 - c))


def path_frames(path: dict, x0, off=(0.0, 0.0, 0.0)):
    """the construction of a swept solid -> (points shifted by -off, joint plane normal at every point oriented along the
    path, [(start index, end index, direction, section plane normal, section x axis) per segment])"""
    pts = [Vector(float(p[0]) - off[0], float(p[1]) - off[1], float(p[2]) - off[2]) for p in path['points']]
    closed = bool(path.get('closed'))
    n = len(pts)
    m = n if closed else n - 1
    if m < 1 or (closed and n < 3):
        raise ValueError('sweep path: needs two points (three when closed)')
    seg = [(k, (k + 1) % n) for k in range(m)]
    scales = path.get('scales')
    step = [(pts[j] - pts[i]).length < 1e-9 for i, j in seg]
    for k, (i, j) in enumerate(seg):
        if step[k] and (scales is None or float(scales[i]) == float(scales[j])):
            raise ValueError('sweep path: two consecutive points coincide (allowed only as a step between two scales)')
    if all(step):
        raise ValueError('sweep path: no length')
    d = [None if step[k] else _unit(pts[j] - pts[i]) for k, (i, j) in enumerate(seg)]
    for k in range(m):                    # a step (the section changes size in place) runs like the segment before it
        if d[k] is None:
            before = [d[q] for q in range(k - 1, -1, -1) if d[q] is not None]
            d[k] = before[0] if before else next(d[q] for q in range(k + 1, m) if d[q] is not None)
    given = path.get('normals') or [None] * n
    if len(given) != n:
        raise ValueError('sweep path: normals needs one entry per point')
    J = []
    for k in range(n):
        din = d[k - 1] if (closed or k > 0) else None
        dout = d[k] if (closed or k < n - 1) else None
        g = given[k]
        if g is None:
            v = dout if din is None else din if dout is None else _unit(din + dout)
        elif g == 'in':
            v = din if din is not None else dout
        elif g == 'out':
            v = dout if dout is not None else din
        else:
            v = _unit(Vector(*[float(c) for c in g]))
            if v.dot(dout if dout is not None else din) < 0:
                v = -v
        J.append(v)
    mode = path.get('section', 'perpendicular')
    if mode not in ('perpendicular', 'joint'):
        raise ValueError('sweep path: section must be "perpendicular" or "joint"')
    secn = [d[k] if mode == 'perpendicular' else J[seg[k][0]] for k in range(m)]
    x = Vector(*[float(c) for c in x0])
    frames = []
    for k in range(m):
        if k:
            x = _carry(x, secn[k - 1], secn[k])
        x = _unit(x - secn[k] * x.dot(secn[k]))
        frames.append((seg[k][0], seg[k][1], d[k], secn[k], x))
    return pts, J, frames


def _fuse(pieces):
    """union of solids that meet on shared faces -> one solid, coplanar neighbouring faces merged"""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    if len(pieces) == 1:
        return pieces[0]
    op = BRepAlgoAPI_Fuse()
    args, tools = _shape_list(), _shape_list()
    args.Append(pieces[0].wrapped)
    for p in pieces[1:]:
        tools.Append(p.wrapped)
    op.SetArguments(args)
    op.SetTools(tools)
    op.SetFuzzyValue(FUZZY)
    op.SetNonDestructive(True)
    op.Build()
    if not op.IsDone():
        raise ValueError('sweep: fusing the segments failed')
    u = ShapeUpgrade_UnifySameDomain(op.Shape(), True, True, False)
    u.Build()
    res = u.Shape()
    out = Solid(res) if res.ShapeType().name == 'TopAbs_SOLID' else Compound(res)
    sols = out.solids()
    if len(sols) == 1:
        return sols[0]
    return Compound(children=list(sols)) if sols else out


def _loops(face):
    """ordered corner points of every wire of a face with straight edges only (outer first), else None"""
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Line
    from OCP.BRep import BRep_Tool
    out = []
    for w in [face.outer_wire()] + list(face.inner_wires()):
        ex, pts = BRepTools_WireExplorer(w.wrapped), []
        while ex.More():
            if BRepAdaptor_Curve(ex.Current()).GetType() != GeomAbs_Line:
                return None
            p = BRep_Tool.Pnt_s(ex.CurrentVertex())
            pts.append((p.X(), p.Y(), p.Z()))
            ex.Next()
        out.append(pts)
    return out


def _loft(fa, fb):
    """the ruled solid between two placements of one section (corresponding corners joined by straight edges): planar
    faces for a polygon section, ruled faces through BRepOffsetAPI_ThruSections otherwise"""
    la, lb = _loops(fa), _loops(fb)
    if la and lb and [len(x) for x in la] == [len(x) for x in lb]:
        faces = [la, lb]
        for a, b in zip(la, lb):
            n = len(a)
            faces += [[[a[i], a[(i + 1) % n], b[(i + 1) % n], b[i]]] for i in range(n)]
        sols = exact_part({'solids': [{'faces': faces}]})
        if len(sols) == 1 and sols[0].is_valid:
            return sols[0]
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    if list(fa.inner_wires()) or list(fb.inner_wires()):
        raise ValueError('sweep: a scaled segment of a section with holes needs a polygon section')
    ts = BRepOffsetAPI_ThruSections(True, True, 1e-6)
    ts.AddWire(fa.outer_wire().wrapped)
    ts.AddWire(fb.outer_wire().wrapped)
    ts.CheckCompatibility(False)
    ts.Build()
    return Solid(ts.Shape()).solids()[0]


def sweep_solid(s: dict, sched: Schedules, off=(0.0, 0.0, 0.0)):
    """one row of solids.csv that has a path in paths.json -> the swept solid, in model coordinates shifted by -off:
    every segment is the profile extruded along it, trimmed by its two joint planes; the segments are fused. With
    "scales" (section "joint" only) the profile is scaled by scales[k] at point k; a segment whose two scales differ is
    the ruled solid between its two end sections. The segments keep OpenCASCADE's default tolerance (no KERNEL_TOL): a
    path is recovered from a faceted source, never from an IFC swept solid the IfcOpenShell kernel evaluates"""
    face = _profile(sched, s['profile_id'])
    sc = _num(s.get('scale'), 1.0)
    if abs(sc - 1.0) > 1e-12:
        face = face.scale(sc)
    path = sched.paths[s['solid_id']]
    pts, J, frames = path_frames(path, (_num(s['xx']), _num(s['xy']), _num(s['xz'])), off)
    scales = path.get('scales')
    if scales is not None and (len(scales) != len(pts) or (path.get('section', 'perpendicular') != 'joint' and len(set(scales)) > 1)):
        raise ValueError('sweep path: scales needs one value per point and section "joint"')
    sized = {}

    def section(k):                               # the profile at the scale of point k
        f = float(scales[k]) if scales is not None else 1.0
        if f not in sized:
            sized[f] = face if f == 1.0 else face.scale(f)
        return sized[f]

    def placed(f, pl):                            # an independent copy of the section on its plane
        return Face(BRepBuilderAPI_Copy(f.moved(Location(pl)).wrapped).Shape())
    pieces = []
    for i, j, d, z, x in frames:
        L = (pts[j] - pts[i]).length
        if L < 1e-9:                              # a step: nothing to build, the neighbours meet in its plane
            continue
        fi = section(i)
        if scales is not None and float(scales[i]) != float(scales[j]):
            zj = J[j]
            xc = _carry(x, z, zj)
            xj = _unit(xc - zj * xc.dot(zj))
            fa = placed(fi, Plane(origin=pts[i], x_dir=x, z_dir=z))
            fb = placed(section(j), Plane(origin=pts[j], x_dir=xj, z_dir=zj))
            pieces.append(_loft(fa, fb))
            continue
        bb = fi.bounding_box()
        reach = max(math.hypot(x_, y_) for x_ in (bb.min.X, bb.max.X) for y_ in (bb.min.Y, bb.max.Y))
        c = min(abs(J[i].dot(d)), abs(J[j].dot(d)))
        if c < 0.02:
            raise ValueError('sweep: a joint plane runs along its segment')
        e = reach / c + 1.0                      # long enough to pass both joint planes everywhere on the section
        base = placed(fi, Plane(origin=pts[i] - d * e, x_dir=x, z_dir=z))
        prism = Solid(BRepPrimAPI_MakePrism(base.wrapped, gp_Vec(*(d * (L + 2 * e)))).Shape())
        prism = _keep_side(prism, tuple(pts[i]), tuple(J[i]))
        prism = _keep_side(prism, tuple(pts[j]), tuple(-J[j]))
        pieces.append(prism)
    return _fuse(pieces)


def _bounded_plane_removed(shape, c: dict, sched: Schedules, off=(0.0, 0.0, 0.0)):
    """the solid a polygon-bounded plane cut removes: the polygon prism through `shape`, on the removed side"""
    P = (_num(c['px'] or 0) - off[0], _num(c['py'] or 0) - off[1], _num(c['pz'] or 0) - off[2])
    b = sched.boundaries[c['cut_id']]
    fr = b['frame']
    outline = _segments_wire(b['outline'])
    face = Face(outline)
    sc = fr.get('scale', 1.0)
    if abs(sc - 1.0) > 1e-12:
        face = face.scale(sc)
    fo = [fr['o'][0] - off[0], fr['o'][1] - off[1], fr['o'][2] - off[2]]
    pl = _plane(fo, fr['x'], fr['z'])
    bb = shape.bounding_box()
    reach = (bb.diagonal + Vector(*fo).sub(bb.center()).length) * 2 + 1000.0
    prism_face = face.moved(Location(pl)).moved(Location(Vector(*fr['z']) * -reach))
    prism = Solid(BRepPrimAPI_MakePrism(_with_kernel_tol(prism_face), gp_Vec(*(Vector(*fr['z']) * 2 * reach))).Shape())
    n = (_num(c['nx']), _num(c['ny']), _num(c['nz']))
    return _keep_side(prism, P, tuple(-v for v in n))


def apply_cut(shape, c: dict, sched: Schedules, off=(0.0, 0.0, 0.0), rules=True):
    kind = c['kind']
    P = (_num(c['px'] or 0) - off[0], _num(c['py'] or 0) - off[1], _num(c['pz'] or 0) - off[2])
    if kind == 'plane':
        return _keep_side(shape, P, (_num(c['nx']), _num(c['ny']), _num(c['nz'])))
    if kind == 'bounded_plane':
        return _cut(shape, _bounded_plane_removed(shape, c, sched, off))
    if kind == 'solid':
        tool = build_solid(sched.solids[c['tool_solid_id']], sched, off, rules)
        return _cut(shape, tool)
    raise ValueError('cut kind ' + kind)


# ---------------------------------------------------------------------------------------- IfcOpenShell boolean rules
# The IfcOpenShell kernel does not apply the cuts of a CSG chain one after the other. It flattens a chain of DIFFERENCE
# booleans into ONE subtraction (first operand minus all second operands), ignores plane cuts that reach less than
# 0.2 mm into the first operand's bounding box, and uses the subtraction only if the result passes its checks (valid,
# manifold, no edges / vertex-edge gaps under 3x the fuzziness, no new near-coincident faces). A rejected result is
# retried with 10x the fuzziness; when no attempt passes, the kernel keeps the FIRST OPERAND UNCHANGED: none of the
# cuts is applied. Kernel units are metres (src/ifcgeom/mapping/IfcBooleanResult.cpp, kernels/opencascade/
# boolean_result.cpp, boolean_utils.cpp, base_utils.cpp of IfcOpenShell 0.8/0.9).
IOS_PRECISION = 1e-5        # m: the kernel's working precision (setting 'precision', default)
IOS_FACE_GAP = 1e-4         # m: near-coincident face check
IOS_MAX_LIST_HALFSPACES = 8
MM = 1000.0                 # schedule units per kernel unit


def _cast(kind, s):
    f = getattr(TopoDS, kind + '_s', None) or getattr(TopoDS, kind)
    return f(s)


def _wrap(sh):
    return Solid(sh) if sh.ShapeType().name == 'TopAbs_SOLID' else Compound(sh)


try:
    from OCP.TopTools import TopTools_IndexedMapOfShape as _ShapeMap
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape as _ShapeListMap
except ImportError:                                          # OCP >= 7.8
    from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as _ShapeMap
    from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as _ShapeListMap


def _indexed(shape, kind):
    from OCP.TopExp import TopExp
    m = _ShapeMap()
    TopExp.MapShapes_s(shape, kind, m)
    return [m.FindKey(i) for i in range(1, m.Extent() + 1)]


def _edge_faces(shape):
    """[(edge, list of its faces)] of a shape (TopExp::MapShapesAndAncestors)"""
    from OCP.TopExp import TopExp
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    m = _ShapeListMap()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, m)
    return [(_cast('Edge', m.FindKey(i)), m.FindFromIndex(i)) for i in range(1, m.Extent() + 1)]


def _degenerate(e):
    from OCP.TopExp import TopExp
    v0, v1 = TopExp.FirstVertex_s(e), TopExp.LastVertex_s(e)
    return not v0.IsNull() and not v1.IsNull() and v0.IsSame(v1)


def _is_manifold(shape) -> bool:
    """util::is_manifold: within every shell each (non-degenerate) edge bounds exactly two faces"""
    from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_SOLID, TopAbs_COMPSOLID
    from OCP.TopoDS import TopoDS_Iterator
    if shape.ShapeType() in (TopAbs_COMPOUND, TopAbs_SOLID, TopAbs_COMPSOLID):
        it = TopoDS_Iterator(shape)
        while it.More():
            if not _is_manifold(it.Value()):
                return False
            it.Next()
        return True
    return all(fs.Extent() == 2 or _degenerate(e) for e, fs in _edge_faces(shape))


def _bbox(shape, gap=0.0):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    b = Bnd_Box()
    BRepBndLib.Add_s(shape, b)
    if gap:
        b.Enlarge(gap)
    return b


def _min_edge_length(shape) -> float:
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.TopAbs import TopAbs_EDGE
    out, ex = math.inf, TopExp_Explorer(shape, TopAbs_EDGE)
    while ex.More():
        e = _cast('Edge', ex.Current())
        if not _degenerate(e):
            g = GProp_GProps()
            BRepGProp.LinearProperties_s(e, g)
            out = min(out, g.Mass())
        ex.Next()
    return out


def _min_vertex_edge_distance(shape, min_search, max_search) -> float:
    """util::min_vertex_edge_distance: smallest vertex-to-edge distance above min_search (vertex not on the edge)"""
    from OCP.TopAbs import TopAbs_VERTEX, TopAbs_EDGE
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.Extrema import Extrema_ExtPC
    from OCP.TopExp import TopExp
    edges = [(e, _bbox(e)) for e in (_cast('Edge', x) for x in _indexed(shape, TopAbs_EDGE))]
    M = math.inf
    for v in (_cast('Vertex', x) for x in _indexed(shape, TopAbs_VERTEX)):
        p, vb = BRep_Tool.Pnt_s(v), _bbox(v, max_search)
        for e, eb in edges:
            if vb.IsOut(eb) or v.IsSame(TopExp.FirstVertex_s(e)) or v.IsSame(TopExp.LastVertex_s(e)):
                continue
            ext = Extrema_ExtPC(p, BRepAdaptor_Curve(e))
            if ext.IsDone():
                for i in range(1, ext.NbExt() + 1):
                    d = math.sqrt(ext.SquareDistance(i))
                    if min_search < d < M:
                        M = d
    return M


def _face_points(f, n=10):
    """points_on_planar_face_generator: 10 x 10 grid over the face's UV bounds, the points strictly inside"""
    from OCP.BRepTools import BRepTools
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt2d
    u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
    surf, tol = BRep_Tool.Surface_s(f), BRep_Tool.Tolerance_s(f)
    out = []
    for j in range(n):
        for i in range(n):
            u, v = u0 + (u1 - u0) * i / n, v0 + (v1 - v0) * j / n
            if BRepClass_FaceClassifier(f, gp_Pnt2d(u, v), tol).State() == TopAbs_IN:
                out.append(surf.Value(u, v))
    return out


def _min_face_face_distance(shape, max_search) -> float:
    """util::min_face_face_distance (planar faces): gap between two (nearly) coplanar faces that overlap"""
    from OCP.TopAbs import TopAbs_FACE, TopAbs_IN
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.gp import gp_Pnt2d, gp_Vec
    faces = []
    for f in (_cast('Face', x) for x in _indexed(shape, TopAbs_FACE)):
        ad = BRepAdaptor_Surface(f, False)
        if ad.GetType() == GeomAbs_Plane:
            faces.append((f, ad.Plane().Position(), _bbox(f)))
    M = math.inf
    for j, (f, pf, bf) in enumerate(faces):
        pts, bfe = None, _bbox(f, max_search)
        for k, (g, pg, bg) in enumerate(faces):
            if k == j or bfe.IsOut(bg) or not pf.IsCoplanar(pg, max_search, math.asin(IOS_FACE_GAP)):
                continue
            pts = _face_points(f) if pts is None else pts
            tol = BRep_Tool.Tolerance_s(g)
            o, x, y, z = pg.Location(), gp_Vec(pg.XDirection()), gp_Vec(pg.YDirection()), gp_Vec(pg.Direction())
            for p in pts:
                d = gp_Vec(o, p)
                if BRepClass_FaceClassifier(g, gp_Pnt2d(d.Dot(x), d.Dot(y)), tol).State() == TopAbs_IN:
                    M = min(M, abs(d.Dot(z)))
    return M


def _operands_nonmanifold(tools, fuzziness) -> bool:
    """the kernel's exemption from the manifold requirement: an edge of one cut operand overlaps another edge and their
    faces do not overlap (the non-manifold result is then what the operands describe)"""
    from OCP.ShapeAnalysis import ShapeAnalysis_Edge
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRep import BRep_Tool
    edges = []
    for t in tools:
        edges += [(e, _bbox(e, fuzziness), [_cast('Face', f) for f in fs]) for e, fs in _edge_faces(t.wrapped)]
    sae = ShapeAnalysis_Edge()

    def faces_overlap(f, g):
        x = BRepExtrema_DistShapeShape()
        x.LoadS1(g)
        eps = BRep_Tool.Tolerance_s(f) + BRep_Tool.Tolerance_s(g)
        for p in _face_points(f):
            x.LoadS2(BRepBuilderAPI_MakeVertex(p).Vertex())
            x.Perform()
            if x.IsDone() and x.NbSolution() == 1 and x.Value() > eps:
                return False
        return True

    for i, (ei, bi, fi) in enumerate(edges):
        for j, (ej, bj, fj) in enumerate(edges):
            if j != i and not bi.IsOut(bj) and (sae.CheckOverlapping(ei, ej, fuzziness, 0.0) or
                                                 sae.CheckOverlapping(ej, ei, fuzziness, 0.0)):
                if not any(faces_overlap(a, b) for a in fi for b in fj):
                    return True
                break
    return False


def _ios_accepts(a, r, tools, fuzziness, scale, a_manifold=None) -> bool:
    """the checks util::boolean_operation applies to a subtraction result (`scale`: shape units per metre;
    `fuzziness` in shape units; `tools` a callable giving the cut operands)"""
    from OCP.BRepCheck import BRepCheck_Analyzer
    if r is None or not BRepCheck_Analyzer(r.wrapped).IsValid():
        return False
    if a_manifold is None:
        a_manifold = _is_manifold(a.wrapped)
    if a_manifold and not _is_manifold(r.wrapped) and not _operands_nonmanifold(tools(), fuzziness):
        return False
    if _min_edge_length(r.wrapped) < fuzziness * 3.0:
        return False
    if _min_vertex_edge_distance(r.wrapped, IOS_PRECISION * scale, fuzziness * 3.0) < fuzziness * 3.0:
        return False
    v = _min_face_face_distance(r.wrapped, IOS_FACE_GAP * scale)
    if v < IOS_FACE_GAP * scale and v < _min_face_face_distance(a.wrapped, IOS_FACE_GAP * scale):
        return False
    return True


def _scaled(shape, k):
    from OCP.gp import gp_Trsf
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    t = gp_Trsf()
    t.SetScaleFactor(k)
    return _wrap(BRepBuilderAPI_Transform(shape.wrapped, t, True).Shape())


def _halfspace_box(a, c, frame, off):
    """util::fit_halfspace: the removed side of a plane cut as a box over the first operand's bounding box (taken in
    the member's own frame, where the kernel evaluates the representation); returns (box, how deep the removed side
    reaches into that bounding box)"""
    P = Vector(_num(c['px']) - off[0], _num(c['py']) - off[1], _num(c['pz']) - off[2])
    n = Vector(-_num(c['nx']), -_num(c['ny']), -_num(c['nz'])).normalized()
    fx, fz = Vector(*frame[0]).normalized(), Vector(*frame[1]).normalized()
    fy = fz.cross(fx)
    b = _bbox(a.moved(Location(Plane(origin=(0, 0, 0), x_dir=fx, z_dir=fz)).inverse()).wrapped, 1e-7 * MM)
    lo, hi = b.CornerMin(), b.CornerMax()
    corners = [fx * X + fy * Y + fz * Z for X in (lo.X(), hi.X()) for Y in (lo.Y(), hi.Y()) for Z in (lo.Z(), hi.Z())]
    pl = Plane(origin=P, z_dir=n)
    us = [(q - P).dot(pl.x_dir) for q in corners]
    vs = [(q - P).dot(pl.y_dir) for q in corners]
    D = max([0.0] + [(q - P).dot(n) for q in corners])
    eps = IOS_PRECISION * 1e3 * 1e3 * MM          # fit_halfspace(tol = precision * 1e3) pads by tol * 1000
    pts = [P + pl.x_dir * (min(us) - eps) + pl.y_dir * (min(vs) - eps), P + pl.x_dir * (max(us) + eps) + pl.y_dir * (min(vs) - eps),
           P + pl.x_dir * (max(us) + eps) + pl.y_dir * (max(vs) + eps), P + pl.x_dir * (min(us) - eps) + pl.y_dir * (max(vs) + eps)]
    face = Face(Wire.make_polygon(pts, close=True))
    return Solid(BRepPrimAPI_MakePrism(face.wrapped, gp_Vec(*(n * (D + eps)))).Shape()), D


def _touching_operands(a, tools, prec):
    """util::eliminate_touching_operands: a planar tool that only touches a planar face of `a` from outside"""
    from OCP.TopAbs import TopAbs_FACE, TopAbs_VERTEX
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.BRepGProp import BRepGProp_Face
    from OCP.BRep import BRep_Tool
    from OCP.gp import gp_Pnt, gp_Vec

    def planar_faces(s):
        fs = [_cast('Face', x) for x in _indexed(s, TopAbs_FACE)]
        return fs if all(BRepAdaptor_Surface(f, False).GetType() == GeomAbs_Plane for f in fs) else None

    def mid_normal(f):
        g = BRepGProp_Face(f)
        u0, u1, v0, v1 = g.Bounds()
        p, v = gp_Pnt(), gp_Vec()
        g.Normal((u0 + u1) / 2.0, (v0 + v1) / 2.0, p, v)
        return p, v

    def pts(s):
        return [(x, BRep_Tool.Pnt_s(_cast('Vertex', x))) for x in _indexed(s, TopAbs_VERTEX)]

    a_faces = planar_faces(a.wrapped)
    if a_faces is None:
        return []
    a_pts = pts(a.wrapped)
    a_info = [(f, _bbox(f), mid_normal(f), [x for x in _indexed(f, TopAbs_VERTEX)]) for f in a_faces]
    out = []
    for t in tools:
        b_faces = planar_faces(t.wrapped)
        if b_faces is None:
            continue
        b_pts = pts(t.wrapped)
        touching = False
        for fb in b_faces:
            bb = _bbox(fb)
            pb, vb = mid_normal(fb)
            fb_v = _indexed(fb, TopAbs_VERTEX)
            for fa, ba, (pa, va), fa_v in a_info:
                if ba.IsOut(bb):
                    continue
                if any((p.XYZ() - pa.XYZ()).Dot(va.XYZ()) > prec for x, p in a_pts if not any(x.IsSame(y) for y in fa_v)):
                    continue
                if va.IsOpposite(vb, 1e-5) and abs((pb.XYZ() - pa.XYZ()).Dot(va.XYZ())) <= prec:
                    if all((p.XYZ() - pa.XYZ()).Dot(va.XYZ()) >= prec * 10.0 for x, p in b_pts if not any(x.IsSame(y) for y in fb_v)):
                        touching = True
                        break
            if touching:
                break
        if touching:
            out.append(t)
    return out


def _ios_subtract(a, tools):
    """util::boolean_operation(CUT) as the kernel runs it, in its units (metres): one subtraction of all tools over the
    fuzziness ladder; returns `a` itself when no attempt passes the checks"""
    from OCP.ShapeFix import ShapeFix_Shape
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.Bnd import Bnd_OBB
    from OCP.BRepBndLib import BRepBndLib

    def unify(s, tol):
        u = ShapeUpgrade_UnifySameDomain(s.wrapped)
        u.SetSafeInputMode(True)
        u.SetLinearTolerance(min(_min_edge_length(s.wrapped) / 2.0, tol))
        u.SetAngularTolerance(1e-3)
        u.Build()
        return _wrap(u.Shape())

    def narrow(t, f):
        o = Bnd_OBB()
        BRepBndLib.AddOBB_s(t.wrapped, o, False, False, False)
        return min(o.XHSize(), o.YHSize(), o.ZHSize()) < f

    A, B = _scaled(a, 1.0 / MM), [_scaled(t, 1.0 / MM) for t in tools]
    f = IOS_PRECISION / 100.0
    while True:                                  # each pass works on the previous pass's (simplified) operands
        A, B = unify(A, f * 1000.0), [unify(t, f) for t in B]
        ab = _bbox(A.wrapped)
        B = [t for t in B if ab.Distance(_bbox(t.wrapped)) < f]                 # disjoint operands are dropped,
        touching = {id(t) for t in _touching_operands(A, B, f)}
        B = [t for t in B if id(t) not in touching and not narrow(t, f)]       # so are touching and narrow ones
        if not B:
            return a                             # "No other operands remaining, using first operand"
        a_manifold = _is_manifold(A.wrapped)
        min_len = min(_min_edge_length(s.wrapped) for s in [A] + B)
        for s in [A] + B:
            min_len = min(min_len, _min_vertex_edge_distance(s.wrapped, IOS_PRECISION, min_len))
        fuzz = min(min_len / 3.0, f)
        op = BRepAlgoAPI_Cut()
        args, tl = _shape_list(), _shape_list()
        args.Append(A.wrapped)
        for t in B:
            tl.Append(t.wrapped)
        op.SetNonDestructive(True)
        op.SetFuzzyValue(fuzz)
        op.SetArguments(args)
        op.SetRunParallel(False)
        op.SetTools(tl)
        op.Build()
        if op.IsDone():
            fx = ShapeFix_Shape(op.Shape())
            fx.SetMaxTolerance(fuzz)
            fx.Perform()
            r = _wrap(fx.Shape())
            if _ios_accepts(A, r, lambda: B, f, 1.0, a_manifold):
                r = _scaled(r, MM)
                sols = r.solids()
                return sols[0] if len(sols) == 1 else (Compound(children=list(sols)) if sols else r)
        nf = f * 10.0
        if not (nf - 1e-15 <= IOS_PRECISION * 1e4 and nf < min_len):
            return a                             # the kernel keeps the first operand: no cut is applied
        f = nf


def _subtract(first, cuts, s, sched, off):
    """one flattened DIFFERENCE boolean: `first` minus all `cuts`, under the kernel's rules"""
    # the frame the source representation is defined in (solids.csv fxx..fzz); older schedules: the solid's own frame
    pre = 'f' if s.get('fxx') not in (None, '') else ''
    frame = tuple(tuple(_num(s[pre + a + b]) for b in 'xyz') for a in 'xz')
    boxes, kept = {}, []
    for c in cuts:
        if c['kind'] == 'plane':
            box, D = _halfspace_box(first, c, frame, off)
            if D < max(20.0 * IOS_PRECISION, 0.00002) * MM:
                continue                        # "Halfspace subtraction yields unchanged volume": ignored
            boxes[c['cut_id']] = box
        kept.append(c)
    shape = first
    for c in kept:                              # construction as before: the cuts one after the other
        shape = apply_cut(shape, c, sched, off)
    if not kept:
        return shape
    cache = []

    def tools():
        if not cache:
            for c in kept:
                if c['kind'] == 'plane':
                    cache.append(boxes[c['cut_id']])
                elif c['kind'] == 'solid':
                    cache.append(build_solid(sched.solids[c['tool_solid_id']], sched, off))
                else:
                    cache.append(_bounded_plane_removed(first, c, sched, off))
        return cache

    if _ios_accepts(first, shape, tools, IOS_PRECISION / 100.0 * MM, MM):
        return shape
    # a result the kernel would not accept: evaluate the boolean the way the kernel does
    return _ios_subtract(first, tools())




def is_manifold(shape) -> bool:
    """every (non-degenerate) edge of every shell bounds exactly two faces (the IfcOpenShell kernel's test of a boolean
    result, util::is_manifold)"""
    return _is_manifold(shape.wrapped)


KERNEL_MIN_EDGE = 1e-4  # mm: OpenCASCADE's confusion tolerance (1e-7 m) in the IfcOpenShell kernel's metre units


def kernel_unbuilt(s: dict, sched: Schedules) -> bool:
    """True for a solid the IfcOpenShell kernel cannot build: an IfcRoundedRectangleProfileDef (RECT with r_outer)
    whose fillets leave a straight side no longer than KERNEL_MIN_EDGE, i.e. RoundingRadius >= min(XDim, YDim) / 2 - 5e-5 mm
    (a full-round slot). The kernel logs GEO027 'Unknown error creating geometry' for it and leaves it out: as a cut or
    opening tool it removes nothing, in the source model and in the STEP the IfcOpenShell kernel wrote (measured on
    IfcOpenShell 0.9.0: radius half - 5e-5 mm fails, half - 1e-4 mm builds)"""
    pr = sched.profiles.get(s.get('profile_id')) or {}
    if pr.get('kind') != 'RECT' or not _num(pr.get('r_outer')):
        return False
    return min(_num(pr.get('b')), _num(pr.get('d'))) - 2.0 * _num(pr.get('r_outer')) <= KERNEL_MIN_EDGE


def build_solid(s: dict, sched: Schedules, off=(0.0, 0.0, 0.0), rules=True):
    """extrusion minus its cuts; `rules`: evaluate the cuts as the IfcOpenShell kernel does (parts that come from the
    source's CSG); without them the cuts are applied one after the other (parts recovered from faceted geometry)"""
    paths = getattr(sched, 'paths', None)
    base = sweep_solid(s, sched, off) if paths and s['solid_id'] in paths else extrude_solid(s, sched, off)
    cuts = sched.cuts_of.get(s['solid_id'], [])
    if rules:
        # a cutting solid the kernel cannot build is not an operand of its boolean (kernel_unbuilt)
        cuts = [c for c in cuts if not (c['kind'] == 'solid' and kernel_unbuilt(sched.solids[c['tool_solid_id']], sched))]
    shape = base
    if not rules:
        for c in cuts:
            shape = apply_cut(shape, c, sched, off, False)
    else:
        # the kernel flattens the chain unless more than 8 half spaces lie below a boolean; such outer booleans are
        # evaluated one by one on the result of the chain inside them (mapping/IfcBooleanResult.cpp)
        n = len(cuts)
        while n > 1 and sum(c['kind'] in ('plane', 'bounded_plane') for c in cuts[:n - 1]) > IOS_MAX_LIST_HALFSPACES:
            n -= 1
        if n:
            shape = _subtract(shape, cuts[:n], s, sched, off)
        for c in cuts[n:]:
            shape = _subtract(shape, [c], s, sched, off)
    # The kernel rejects a boolean result that is not manifold (an edge shared by more than two faces, e.g. a clipped-off
    # wedge left touching the body along a line) unless its manifold exemption applies, and after its fuzziness retries
    # keeps the first operand, so the solid keeps its uncut extrusion (openings are still subtracted afterwards). The
    # rules above evaluate the kernel's 3D path only. Before it, the kernel subtracts in 2D every operand that is an
    # extrusion through the whole first operand (boolean_utils.cpp, attempt_2d: "Operand B creates a through hole") and
    # then judges only the remaining operands: its manifold exemption looks at their edges alone and its retries run on
    # them alone. Where that decides (a Revit wall whose three polygon-bounded cuts give a non-manifold notch: two of
    # them are through holes, the exemption sees one operand, every retry is non-manifold, the kernel keeps the wall
    # uncut), a non-manifold result of a manifold extrusion gives the extrusion, as the kernel does.
    if cuts and not is_manifold(shape) and is_manifold(base):
        return base
    return shape


def _poly_wire(pts):
    mp = BRepBuilderAPI_MakePolygon()
    for p in pts:
        mp.Add(gp_Pnt(*p))
    mp.Close()
    return mp.Wire()


def _planar_face(loops):
    """face through the given loops on their best-fit plane (Newell normal); vertices are kept as given"""
    outer = loops[0]
    n = [0.0, 0.0, 0.0]
    m = len(outer)
    for i in range(m):
        a, b = outer[i], outer[(i + 1) % m]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    c = [sum(p[k] for p in outer) / m for k in range(3)]
    pln = gp_Pln(gp_Pnt(*c), gp_Dir(*n))
    mf = BRepBuilderAPI_MakeFace(pln, _poly_wire(outer), True)
    for h in loops[1:]:
        mf.Add(_poly_wire(h))
    fix = ShapeFix_Face(mf.Face())
    fix.FixOrientation()
    fix.Perform()
    return fix.Face()


SEW_TOL = 1e-3                      # mm: facet sewing tolerance; a closed faceted body sews at this
SEW_RETRY_TOLS = (1e-2, 1e-1, 1.0)  # mm: last-resort re-sewing of a body the source leaves open (see _closed_shell)


def _sew(faces, tol):
    """faces sewn at `tol` -> ([shells, each through ShapeFix_Shell], sewn shape)"""
    sew = BRepBuilderAPI_Sewing(tol)
    for fc in faces:
        sew.Add(fc)
    sew.Perform()
    sewn = sew.SewedShape()
    out = []
    ex = TopExp_Explorer(sewn, TopAbs_SHELL)
    while ex.More():
        fx = ShapeFix_Shell(_cast('Shell', ex.Current()))
        fx.Perform()
        out.append(fx.Shell())
        ex.Next()
    return out, sewn


def _shell_closed(sh) -> bool:
    """BRepCheck_Shell.Closed: every edge of the shell bounds two of its faces (what a valid solid needs of its shell)"""
    from OCP.BRepCheck import BRepCheck_Shell, BRepCheck_NoError
    return BRepCheck_Shell(_cast('Shell', sh)).Closed() == BRepCheck_NoError


def _shell_faces(sh):
    from OCP.TopAbs import TopAbs_FACE
    return _indexed(sh, TopAbs_FACE)


def _free_loops(sh):
    """the free boundary of a sewn shell (edges of one face only) -> ([closed loops as vertex lists], number of edges
    in open chains)"""
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_WIRE
    fb = ShapeAnalysis_FreeBounds(sh, False, True, False)
    loops, ex = [], TopExp_Explorer(fb.GetClosedWires(), TopAbs_WIRE)
    while ex.More():
        pts, we = [], BRepTools_WireExplorer(_cast('Wire', ex.Current()))
        while we.More():
            q = BRep_Tool.Pnt_s(we.CurrentVertex())
            pts.append((q.X(), q.Y(), q.Z()))
            we.Next()
        loops.append(pts)
        ex.Next()
    return loops, len(_indexed(fb.GetOpenWires(), TopAbs_EDGE))


def _same_loop(a, b):
    """the same vertices (each within SEW_TOL of one of the other's)"""
    return len(a) == len(b) and all(any(math.dist(p, q) <= SEW_TOL for q in b) for p in a) and \
        all(any(math.dist(q, p) <= SEW_TOL for p in a) for q in b)


def _loop_closures(sh, faces, others):
    """the faces that close the free loops of the open shell `sh` (sewn from the source polygons `faces` of one body),
    taken from the source only -> ([face per loop], [how per loop]) or (None, None) unless every loop has one:
      'source_face'  a face of the same part outside this body (`others`) with exactly the loop's vertices: the source
                     lists once a face that two of its bodies share (pinewood weld 3YRc4tbvzBFOvsS9BPKmlx: two beads on
                     one cap face that the delivered file keeps as a separate one-face sheet)
      'corner'       the loop itself, as the polygon of its source vertices, when it lies within SEW_TOL in the plane of
                     the source face that has one of its edges: that face's polygon skips a corner vertex which its
                     neighbouring faces use (cmc Model1 bolts: 17 facets where a closed body needs 18; the skipped
                     corner a 3.08 mm2 triangle 0.78 mm high in the plane of its face)"""
    loops, n_open = _free_loops(sh)
    if not loops or n_open:
        return None, None
    src = [tuple(p) for fc in faces for lp in fc for p in lp]
    out, how = [], []
    for lp in loops:
        hit = next((fc for fc in others if len(fc) == 1 and _same_loop(fc[0], lp)), None)
        if hit is not None:
            out.append(hit)
            how.append('source_face')
            continue
        snapped = []
        for p in lp:                              # the loop's vertices are source vertices (sewing merged them within SEW_TOL)
            q = min(src, key=lambda s: math.dist(s, p))
            snapped.append(q if math.dist(q, p) <= SEW_TOL else None)
        if len(snapped) < 3 or any(p is None for p in snapped):
            return None, None
        m = len(snapped)
        edges = [(snapped[j], snapped[(j + 1) % m]) for j in range(m)]
        corner = False
        for fc in faces:
            o = [tuple(p) for p in fc[0]]
            n = len(o)
            if not any(math.dist(o[i], a) <= SEW_TOL and math.dist(o[(i + 1) % n], b) <= SEW_TOL or
                       math.dist(o[i], b) <= SEW_TOL and math.dist(o[(i + 1) % n], a) <= SEW_TOL
                       for i in range(n) for a, b in edges):
                continue
            nrm, c = _plane_of([o])
            if nrm is not None and _flatness([o, snapped], nrm, c) <= SEW_TOL:
                corner = True
                break
        if not corner:
            return None, None
        out.append([[list(p) for p in snapped]])
        how.append('corner')
    return out, how


def _closed_shell(sh, faces, others):
    """an open shell sewn at SEW_TOL, closed from the source only -> (closed shell, how) or (None, None):
      1. its free loops closed by source faces (_loop_closures), all sewn at SEW_TOL: exact - the closed solid is the
         polyhedron of source vertices, the same in memory and in the STEP file written from it;
      2. last resort (issue #7 patch): its faces re-sewn at the coarser SEW_RETRY_TOLS, the first that closes it. This
         bridges the gap by edge tolerance: STEP carries no tolerances, so the file can read back as a slightly
         different solid (cmc Model1 bolts re-sewn: +1.31e-4 of the part's volume on read-back) - e2e.py reports it.
    A result counts only as one closed shell holding every face (none dropped or merged)."""
    sfaces = _shell_faces(sh)
    extra, how = _loop_closures(sh, faces, others)
    if extra:
        res, _ = _sew(sfaces + [_planar_face(fc) for fc in extra], SEW_TOL)
        if len(res) == 1 and _shell_closed(res[0]) and len(_shell_faces(res[0])) == len(sfaces) + len(extra):
            return res[0], '+'.join(sorted(set(how)))
    for tol in SEW_RETRY_TOLS:
        res, _ = _sew(sfaces, tol)
        if len(res) == 1 and _shell_closed(res[0]) and len(_shell_faces(res[0])) == len(sfaces):
            return res[0], f'resewn_{tol:g}mm'
    return None, None


def _shells(faces, others=None, report=None):
    """sew planar faces into shells (several if the faces form several closed bodies). A shell left open is closed
    from the source only (_closed_shell; `others`: the part's faces outside this body, or a callable giving them);
    shells that close at SEW_TOL are never touched, and a shell that cannot be closed stays as sewn (its solid is
    then invalid and verification reports it). `report` (a list) receives (shell index, how) per shell left open"""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Shell
    out, sewn = _sew([_planar_face(fc) for fc in faces], SEW_TOL)
    src = None
    for k, sh in enumerate(out):
        if _shell_closed(sh):
            continue
        if src is None:
            src = list(others()) if callable(others) else list(others or [])
        fixed, how = _closed_shell(sh, faces, src)
        if fixed is not None:
            out[k] = fixed
        if report is not None:
            report.append((k, how or 'open'))
    if not out:                                   # nothing sewn: one shell of all faces
        bld, sh = BRep_Builder(), TopoDS_Shell()
        bld.MakeShell(sh)
        from OCP.TopAbs import TopAbs_FACE
        fe = TopExp_Explorer(sewn, TopAbs_FACE)
        while fe.More():
            bld.Add(sh, fe.Current())
            fe.Next()
        out.append(sh)
    return out


def _newell(loop):
    n = [0.0, 0.0, 0.0]
    m = len(loop)
    for i in range(m):
        a, b = loop[i], loop[(i + 1) % m]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    return n


def _plane_of(loops):
    outer = loops[0]
    n = _newell(outer)
    ln = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)
    if ln == 0.0:
        return None, None
    n = (n[0] / ln, n[1] / ln, n[2] / ln)
    c = tuple(sum(p[k] for p in outer) / len(outer) for k in range(3))
    return n, c


def _flatness(loops, n, c):
    d = [(p[0] - c[0]) * n[0] + (p[1] - c[1]) * n[1] + (p[2] - c[2]) * n[2] for lp in loops for p in lp]
    return max(d) - min(d)


def _is_sheet(faces):
    """all faces lie in one plane (within 0.001 mm): they bound no volume - a stray surface of the delivered file, not a body"""
    big = max(faces, key=lambda fc: sum(v * v for v in _newell(fc[0])))
    n, c = _plane_of(big)
    return n is None or _flatness([lp for fc in faces for lp in fc], n, c) <= 1e-3


def _outward(res, raw):
    """volume-sign check after ShapeFix_Solid: a closed solid encloses a positive volume. ShapeFix_Solid orients a solid
    by classifying a point against it, which can fail on a large solid far from the origin and leave it inside out (seen
    on the source side of verification: a 141 m3 slab). A closed solid of negative volume is replaced by the unfixed
    solid when that one is closed and positive, else by itself reversed. An open solid has no defined volume: it is left
    as it is (verification reports it invalid)"""
    from OCP.TopAbs import TopAbs_SOLID
    shells = _indexed(res, TopAbs_SHELL)
    if not shells or not all(_shell_closed(s) for s in shells) or _volume(res) >= 0.0:
        return res
    rsh = _indexed(raw, TopAbs_SHELL)
    if _indexed(raw, TopAbs_SOLID) and rsh and all(_shell_closed(s) for s in rsh) and _volume(raw) > 0.0:
        return raw
    return _cast('Solid', res.Reversed())


def exact_part(rec: dict, report=None):
    """faceted solids from exact polygon faces: {'solids': [{'faces': [[outer, hole, ...], ...], 'voids': [...]}]}.
    A body the source leaves open is closed from the source only (see _shells); one that cannot be closed is kept as an
    (invalid) solid, never dropped and never handed on as a shell. Every closed solid comes out with a positive volume
    (_outward). `report` (a list) receives (source solid index, 'outer' | 'void', shell index, how) for every shell that
    did not close when sewn (how: see _closed_shell, or 'open')"""
    from OCP.TopAbs import TopAbs_SOLID
    out = []
    sol = rec['solids']
    for k, so in enumerate(sol):
        if _is_sheet(so['faces']):
            continue
        rep = [] if report is not None else None
        shells = _shells(so['faces'], lambda k=k: [fc for j, s2 in enumerate(sol) if j != k for fc in s2['faces']], rep)
        voids = []
        for vd in so.get('voids', []):
            vrep = [] if report is not None else None
            voids += _shells(vd, None, vrep)
            if vrep:
                report += [(k, 'void', i, how) for i, how in vrep]
        if rep:
            report += [(k, 'outer', i, how) for i, how in rep]
        for i, sh in enumerate(shells):
            mk = BRepBuilderAPI_MakeSolid(sh)
            if i == 0:
                for v in voids:
                    mk.Add(v)
            raw = mk.Solid()
            fix = ShapeFix_Solid(raw)
            fix.Perform()
            res = fix.Solid()
            # ShapeFix can hand back the shell instead of a solid (an open shell is valid as a shell, so the part would
            # read as valid and its volume would be skipped): keep the solid, whose invalidity is then reported
            if not _indexed(res, TopAbs_SOLID):
                res = raw
            out.append(Solid(_outward(res, raw)))
    return out


def build_part(part: dict, sched: Schedules) -> list:
    """all solids of one part"""
    pid = part['part_id']
    if part.get('geometry') == 'exact':
        return exact_part(sched.exact[pid])
    body = sched.body_of.get(pid, [])
    if not body:
        return []
    # booleans run around the part's own origin (models can sit hundreds of metres from the global origin, where
    # OpenCASCADE loses the precision small cuts need); the finished part is then moved back into place
    s0 = sched.solids[body[0]]
    off = (round(_num(s0['ox'])), round(_num(s0['oy'])), round(_num(s0['oz'])))
    rules = part.get('geometry', 'parametric') == 'parametric'
    solids = [build_solid(sched.solids[sid], sched, off, rules) for sid in body]
    for o in sched.open_of.get(pid, []):
        for tid in o['tool_solids'].split():
            if rules and kernel_unbuilt(sched.solids[tid], sched):
                continue                        # an opening the kernel cannot build removes nothing (kernel_unbuilt)
            tool = build_solid(sched.solids[tid], sched, off, rules)
            solids = [_cut(s, tool) for s in solids]
    if any(off):
        solids = [s.moved(Location(Vector(*off))) for s in solids]
    return solids


def build_model(folder: str, only=None, progress=None):
    """yields (part row, [solids]) for every part (or the part ids in `only`)"""
    sched = Schedules(folder)
    for i, p in enumerate(sched.parts):
        if only and p['part_id'] not in only:
            continue
        yield p, build_part(p, sched)
        if progress and i % 200 == 0:
            progress(i, len(sched.parts))


def _edge_face_map():
    """an indexed map shape -> list of ancestor shapes (OCP version safe)"""
    try:
        from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape          # OCP < 7.8
        return TopTools_IndexedDataMapOfShapeListOfShape()
    except ImportError:
        from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher
        return IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher()


def _snap_vertices(shape):
    """for export: a boolean run with the kernel tolerance can leave an edge's curve ending up to a few micrometres away
    from its vertex (the vertex tolerance covers the gap). In memory the edge is bounded by its curve parameters; STEP
    stores an edge as vertex points plus a curve, and the reader re-derives the parameter range by projecting the vertices
    onto the curve, so such an edge comes back longer or shorter and the face it bounds changes its area (a part read back
    with a different volume and centre). Move each such vertex, within its own tolerance, to the point whose projection onto
    every incident edge curve is that edge's own end parameter (least squares over the edges' end tangents), so the reader
    reproduces the in-memory edge ranges. Only vertices off a curve end by more than SNAP_GAP move; curves, surfaces and
    pcurves are untouched, so the copy's volume and centre are the in-memory ones. Works on (and returns) the given copy."""
    import numpy as np
    from OCP.TopExp import TopExp
    from OCP.BRep import BRep_Tool, BRep_Builder
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopLoc import TopLoc_Location
    loc = shape.Location()
    base = shape.Located(TopLoc_Location())
    vtx = TopoDS.Vertex_s if hasattr(TopoDS, 'Vertex_s') else TopoDS.Vertex
    edg = TopoDS.Edge_s if hasattr(TopoDS, 'Edge_s') else TopoDS.Edge
    off = []                                         # vertices off a curve end (quick scan; most parts have none)
    ex = TopExp_Explorer(base, TopAbs_EDGE)
    while ex.More():
        e = edg(ex.Current())
        ex.Next()
        if BRep_Tool.Degenerated_s(e):
            continue
        c = BRepAdaptor_Curve(e)
        for v, u in ((TopExp.FirstVertex_s(e), c.FirstParameter()), (TopExp.LastVertex_s(e), c.LastParameter())):
            if not v.IsNull() and BRep_Tool.Pnt_s(v).Distance(c.Value(u)) > SNAP_GAP and not any(v.IsSame(w) for w in off):
                off.append(v)
    if not off:
        return shape
    m = _edge_face_map()
    TopExp.MapShapesAndAncestors_s(base, TopAbs_VERTEX, TopAbs_EDGE, m)
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopAbs import TopAbs_FACE
    fce = TopoDS.Face_s if hasattr(TopoDS, 'Face_s') else TopoDS.Face
    mf = _edge_face_map()                            # vertex -> faces: a snapped vertex stays on its faces' planes
    TopExp.MapShapesAndAncestors_s(base, TopAbs_VERTEX, TopAbs_FACE, mf)
    bld = BRep_Builder()
    for i in range(1, m.Extent() + 1):
        v = vtx(m.FindKey(i))
        if not any(v.IsSame(w) for w in off):
            continue
        p0 = BRep_Tool.Pnt_s(v)
        v0 = np.array([p0.X(), p0.Y(), p0.Z()])
        rows, rhs, seen, gap = [], [], [], 0.0
        for e in m.FindFromIndex(i):
            e = edg(e)
            if BRep_Tool.Degenerated_s(e) or any(e.IsSame(x) for x in seen):
                continue
            seen.append(e)
            c = BRepAdaptor_Curve(e)
            ends = ([c.FirstParameter()] if TopExp.FirstVertex_s(e).IsSame(v) else []) + \
                   ([c.LastParameter()] if TopExp.LastVertex_s(e).IsSame(v) else [])
            for u in ends:
                p, d = gp_Pnt(), gp_Vec()
                c.D1(u, p, d)
                if d.Magnitude() < 1e-12:
                    continue
                pe = np.array([p.X(), p.Y(), p.Z()])
                gap = max(gap, float(np.linalg.norm(pe - v0)))
                dn = np.array([d.X(), d.Y(), d.Z()]) / d.Magnitude()
                rows.append(dn)
                rhs.append(float(dn @ pe))
        if not rows or gap <= SNAP_GAP:
            continue
        # the vertex must stay on the plane of every planar face it bounds (the STEP reader rebuilds a face through its
        # vertices: a vertex moved off the plane changes the face's area - seen 1.7e-5 of a weld's volume)
        prow, prhs = [], []
        j = mf.FindIndex(v)
        for f in (mf.FindFromIndex(j) if j else []):
            ad = BRepAdaptor_Surface(fce(f))
            if ad.GetType() == GeomAbs_Plane:
                pl = ad.Plane()
                nd, po = pl.Axis().Direction(), pl.Location()
                nn = np.array([nd.X(), nd.Y(), nd.Z()])
                prow.append(1e3 * nn)
                prhs.append(1e3 * float(nn @ np.array([po.X(), po.Y(), po.Z()])))
        a = np.vstack(rows + prow + [1e-4 * np.eye(3)])     # weak pull to the current point fixes free directions
        b = np.concatenate([rhs, prhs, 1e-4 * v0])
        vn = np.linalg.lstsq(a, b, rcond=None)[0]
        tol = BRep_Tool.Tolerance_s(v)
        if float(np.linalg.norm(vn - v0)) <= tol:
            bld.UpdateVertex(v, gp_Pnt(*(float(x) for x in vn)), tol)
    return base.Located(loc)


SNAP_GAP = 1e-6     # mm


def _own(shape):
    """deep copy: every solid gets its own geometry, so the STEP writer never merges solids that share data; vertices that
    sit off their edges' curve ends are snapped for the STEP reader (see _snap_vertices)"""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    return Solid(_snap_vertices(BRepBuilderAPI_Copy(shape.wrapped, True, False).Shape()))


def _free_edges(shape) -> int:
    """edges of a shape bounded by one face only (an open shell's boundary); degenerate edges are not counted, and a seam
    lists its face twice"""
    from OCP.BRep import BRep_Tool
    return sum(1 for e, fl in _edge_faces(shape) if not BRep_Tool.Degenerated_s(e) and sum(1 for _ in fl) == 1)


def solid_defects(solid) -> str:
    """'' for a valid closed solid, else what is wrong with it: 'invalid' (BRepCheck, in the solid's own frame: the frame
    a STEP file defines its B-rep in, before the placement that carries it up to ~500 m from the origin) and/or 'open'
    (a free edge)"""
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopLoc import TopLoc_Location
    base = solid.wrapped.Located(TopLoc_Location())
    bad = [] if BRepCheck_Analyzer(base).IsValid() else ['invalid']
    if _free_edges(base):
        bad.append('open')
    return ', '.join(bad)


def write_step(items, path: str, name: str = '', report=None) -> int:
    """items: [(part row, [solids])] -> one STEP file, one labelled product per part. Returns the number of solids handed
    to it that are not valid (BRepCheck) or not closed (a free edge), each also reported on stderr: STEP writers and
    readers can drop such a solid without notice (an open solid has no volume), so the file read back may lack it.
    `report` (a list) receives (part id, solid index, 'invalid' | 'open' | 'invalid, open') for every such solid. Every
    solid is written. (The check is made on the solids as built: the copy written has its vertices snapped for the STEP
    reader, which can upset BRepCheck in memory while the file reads back valid - e2e.py checks the file itself.)"""
    import sys
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    children, bad = [], 0
    for p, solids in items:
        for k, s in enumerate(solids):
            why = solid_defects(s)
            if why:
                bad += 1
                print(f"write_step: part {p['part_id']} solid {k + 1} of {len(solids)} is {why}: a STEP reader may drop it",
                      file=sys.stderr)
                if report is not None:
                    report.append((p['part_id'], k, why))
        own = [_own(s) for s in solids]
        if len(own) == 1:
            c = own[0]
        else:
            bld, comp = BRep_Builder(), TopoDS_Compound()
            bld.MakeCompound(comp)
            for s in own:
                bld.Add(comp, s.wrapped)
            c = Compound(comp)
        c.label = f"{p['part_id']} {p['name']}".strip()
        children.append(c)
    export_step(Compound(children=children, label=name or os.path.basename(path)), path)
    return bad
