#!/usr/bin/env python3
"""Recover faceted parts that are a straight extrusion modified by cut-outs:  BODY prism  minus  CUT TOOLS.

recover.py accepts a faceted part when it is one straight extrusion whose ends are single planes. Members with copes,
notches, slots, holes across the axis, stepped or many-faceted ends, walls with openings ... fail that test. This module
is its fallback. For one source solid S (exact polygon faces) it searches a construction

    body  = section x axis x length            the section is the envelope of S along the axis: the union of the
            - supporting end planes            projections of S's faces (exact source vertices); an end plane is a
                                               plane of one of S's end faces with all of S on one side of it
    tools = R_1 ... R_k                        the connected pieces of  body - S  (the material the cut-outs remove)
    S     = body - R_1 - ... - R_k

and every tool R_i is recovered the same way (its own axis, envelope section, end planes and, one level deeper, its own
tools), so a tool is again a prism with plane cuts, optionally minus sub-tools (e.g. a headed stud: head-size prism
minus a ring prism around the shank, minus the chamfer ring that stays). Nothing is assumed: every section vertex is a
projected source vertex (or the crossing of two projected source edges), every plane is a source face plane.

Accepted only when the solid rebuilt by steelbuild from the schedule rows (the exact code path of build_model.py,
schedules -> build_part) passes recover.coincide - the acceptance test of every recovered part (recover.py: bounding
box, centroid, vertex gap, symmetric difference per surface area, with try_part's limits) - and, stricter, the same
construction moved by small odd offsets (other float rounding, as on another machine) passes it again: booleans of
coincident faces that only work by luck are rejected. Otherwise the part stays exact. The search itself (which body,
which pieces, which tools) uses its own quicker coincidence test (search_coincide) only to choose a candidate.

The search is deterministic: candidate axes, pieces and planes are sorted by geometric keys; limits are counts
(depth, tools, faces of the solid and of each cut-out piece, measurement configurations, unsound measurements, and
MAX_OPS: the number of OpenCASCADE booleans / 2D unions / trial constructions the search may run for one part), never
time. The acceptance (recover.coincide on the final construction, and the stability shifts) is not part of the budget.

API:  try_cut_tools(rec) -> (list of solid descriptions | None, reason)       (rec: one exact_geometry.jsonl record)
      a description: o, x, z, vec, profile | outline, cuts (plane cuts), tools (descriptions of the cut tools);
      recover.emit writes its schedule rows
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'kit'))

LAT_TOL = 0.004          # |n . axis| below this: side face (as recover.py)
SUPPORT_TOL = 0.02       # mm: an end plane may cut away nothing of the source beyond this (source grid 0.01 mm)
SEARCH_SYMDIFF = 0.005   # search only (search_coincide): symmetric difference / volume of a candidate worth checking
SEARCH_BBOX = 0.05       # search only: mm
MAX_DEPTH = 2            # body -> tools -> sub-tools
MAX_TOOLS = 48           # per body / tool
MAX_AXES = (3, 2, 2)     # candidate axes tried at depth 0, 1, 2
# Size and budget limits (counts, so the search is deterministic). Measured on all 4,702 exact parts of the 33 models
# (v7, every search run to its end or for 4 minutes): every construction the search found was for a solid of at most
# 623 faces and took at most 462 operations; on larger solids a single OpenCASCADE boolean of the solid against its
# envelope takes 20 - 600 s (the envelope's faces lie on the solid's own faces, within the source's 0.01 mm grid), the
# 2D union of its facet projections (envelope) grows past 7 GB (from 932 faces up), and no search found a construction.
# A solid above MAX_FACES is therefore not searched (it stays exact) - tools included (solve) - and the search of one
# part stops after MAX_OPS operations.
MAX_FACES = 640          # larger faceted solids are not searched
MAX_OPS = 480            # search budget per part (booleans, 2D unions, trial constructions): see the module docstring
# Three more counts bound the searches that cannot succeed, measured on every search of the 33 models that found a
# construction (474 distinct parts, instrumented): the largest cut-out piece any of them met had 94 faces (failed
# searches went on into pieces of 300 - 576 faces, as complex as the part, whose own searches ran the longest booleans:
# 70 - 104 s each); every sound piece measurement came in the first 4 of the 9 frame / fuzzy configurations (3,925 of
# 3,942 in the first, none beyond the 4th: when the first 4 fail the others did too); and no search met more than 6
# piece measurements without a sound configuration. Each limit is about twice what was seen, so no search that found a
# construction comes near one.
MAX_TOOL_FACES = 192     # a cut-out piece (a tool to recover) with more faces is not searched
PIECE_TRIES = 6          # configurations tried for one piece measurement (cut_pieces) before it counts as unsound
MAX_UNSOUND = 12         # unsound piece measurements after which the search of the part stops
MAX_CAP_PLANES = 64      # distinct end planes on one prism
PIECE_TOL = 1e-3         # X - body and the volume balance of body - X, relative to X (grid-level deviations)
PIECE_MIN_REL = 1e-6     # pieces of body - S smaller than this fraction of S: numerical slivers
PIECE_MIN_THICK = 0.02   # mm: pieces thinner than this on average (2 V / A): facet noise, not cut-outs
_DEBUG = bool(os.environ.get('RECOVER_CUTS_DEBUG'))


def _dbg(*a):
    if _DEBUG:
        print('[rc]', *a, file=sys.stderr, flush=True)


# ======================================================================================== polygon geometry (numpy)
def newell(lp):
    p = np.asarray(lp, float)
    q = np.roll(p, -1, axis=0)
    return np.array([np.sum((p[:, 1] - q[:, 1]) * (p[:, 2] + q[:, 2])), np.sum((p[:, 2] - q[:, 2]) * (p[:, 0] + q[:, 0])),
                     np.sum((p[:, 0] - q[:, 0]) * (p[:, 1] + q[:, 1]))])


class Poly:
    """a closed polyhedron given by planar polygon faces (outer loop + hole loops), outward normals"""

    def __init__(self, faces):
        self.faces = [[np.asarray(lp, float) for lp in fc] for fc in faces if len(fc) and len(fc[0]) >= 3]
        n = len(self.faces)
        self.N = np.zeros((n, 3))
        self.A = np.zeros(n)
        self.C = np.zeros((n, 3))
        for i, fc in enumerate(self.faces):
            v = newell(fc[0])
            for h in fc[1:]:
                v = v + newell(h)
            a = np.linalg.norm(v) / 2.0
            self.A[i] = a
            self.N[i] = v / (2 * a) if a > 0 else v
            self.C[i] = fc[0].mean(0)
        self.P = np.concatenate([lp for fc in self.faces for lp in fc]) if n else np.zeros((0, 3))
        # orientation: the loops of a valid closed polyhedron give a positive signed volume when wound outward
        o = self.P.mean(0) if len(self.P) else np.zeros(3)
        sv = 0.0
        for fc in self.faces:
            for lp in fc:
                q = lp - o
                sv += np.einsum('ij,ij->', q[:1].repeat(len(q) - 2, 0), np.cross(q[1:-1], q[2:])) / 6.0
        if sv < 0:
            self.N = -self.N
        self.volume = abs(sv)
        # supporting faces: the whole solid lies on the inner side of the face plane (convex directions); a face that
        # is not supporting bounds a cut-out (cope, notch, hole, step) whatever the extrusion axis
        self.supp = np.ones(n, bool)
        for i in range(n):
            if self.A[i] > 0:
                self.supp[i] = float(np.max((self.P - self.C[i]) @ self.N[i])) <= SUPPORT_TOL
        # coplanar faces share a plane id (an end cut split into facets is one plane)
        self.plane = np.zeros(n, int)
        RN, RC = np.zeros((0, 3)), np.zeros((0, 3))
        for i in sorted(range(n), key=lambda i: (-self.A[i], i)):
            if len(RN):
                m = (RN @ self.N[i] > 1 - 1e-6) & (np.abs(np.einsum('ij,ij->i', self.C[i] - RC, RN)) < 1e-3)
                if m.any():
                    self.plane[i] = int(np.argmax(m))
                    continue
            self.plane[i] = len(RN)
            RN, RC = np.vstack([RN, self.N[i]]), np.vstack([RC, self.C[i]])


def axis_candidates(poly, k):
    """unit axes, best first: normals of the largest faces and their cross products, each refined to the least-squares
    direction of the faces that are side faces for it; ranked by the area of end faces that are not supporting planes
    (they need cut tools), then by the number of end planes, then by side-face area"""
    N, A = poly.N, poly.A
    order = np.argsort(-A, kind='stable')[:10]
    raw = []
    for i in range(len(order)):
        for j in range(i + 1, len(order)):
            c = np.cross(N[order[i]], N[order[j]])
            if np.linalg.norm(c) > 0.05:
                raw.append(c / np.linalg.norm(c))
    for i in order[:6]:
        if np.linalg.norm(N[i]) > 0.5:
            raw.append(N[i] / np.linalg.norm(N[i]))
    out = []
    for a in raw:
        lat = np.abs(N @ a) < LAT_TOL * 5
        if lat.sum() < 2:
            continue
        S = (N[lat].T * A[lat]) @ N[lat]
        w, v = np.linalg.eigh(S)
        b = v[:, 0]
        if np.dot(b, a) < 0:
            b = -b
        if b[np.argmax(np.abs(b))] < 0:          # canonical sign: largest component positive
            b = -b
        if any(abs(np.dot(b, c)) > 1 - 1e-9 for c, _ in out):
            continue
        lat = np.abs(N @ b) < LAT_TOL
        bad = float(A[~lat & ~poly.supp].sum())
        nplanes = len(set(poly.plane[~lat].tolist()))
        out.append((b, (round(bad, 3), nplanes, -round(float(A[lat].sum()), 3), tuple(np.round(b, 9)))))
    out.sort(key=lambda x: x[1])
    return [b for b, _ in out[:k]]


def frame_for(poly, a):
    lat = np.abs(poly.N @ a) < LAT_TOL
    big = int(np.argmax(np.where(lat, poly.A, -1)))
    u = np.cross(poly.N[big], a)
    if np.linalg.norm(u) < 1e-6:
        u = np.cross(a, [1.0, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 1.0, 0])
    u /= np.linalg.norm(u)
    v = np.cross(a, u)
    return u, v


def area2(p):
    return 0.5 * float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]))


def simplify2(p, tol=1e-6):
    """drop repeated and collinear points (keeps the remaining source vertices unchanged): repeatedly the first point
    (in loop order) collinear with its neighbours goes; the scan resumes at the point before it (at 0 when the last
    point went) instead of restarting - the same points in the same order, in linear time (as recover.simplify)"""
    pts = [q for i, q in enumerate(p) if np.linalg.norm(q - p[i - 1]) > 1e-9] if len(p) > 1 else list(p)
    i = 0
    while len(pts) > 3 and i < len(pts):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
        if abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < tol * max(1.0, np.linalg.norm(c - a)):
            pts.pop(i)
            i = 0 if i >= len(pts) else max(i - 1, 0)
        else:
            i += 1
    return np.asarray(pts)


# ======================================================================================== OpenCASCADE helpers
_OPS = [0]              # search operations spent on the current part (reset by try_cut_tools)
_UNSOUND = [0]          # piece measurements of the current part without a sound configuration (reset by try_cut_tools)


def _spend():
    """count one search operation; past MAX_OPS the search of this part stops (the part stays exact)"""
    _OPS[0] += 1
    if _OPS[0] > MAX_OPS:
        raise _Fail('search budget exceeded')


def _reraise_oom(e):
    """an allocation that failed under the worker's memory limit is not a refused construction: it ends the part"""
    import recover
    if recover.is_oom(e):
        raise e


def _ocp():
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Common, BRepAlgoAPI_Fuse
    return BRepAlgoAPI_Cut, BRepAlgoAPI_Common, BRepAlgoAPI_Fuse


def volume(shape):
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped if hasattr(shape, 'wrapped') else shape, g)
    return g.Mass()


def copy_shape(s):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    return BRepBuilderAPI_Copy(s, True, False).Shape()


def bop(kind, a, b, fuzzy):
    """boolean on fresh copies, inputs untouched (OpenCASCADE booleans may otherwise alter shared sub-shapes and make
    later results depend on earlier ones)"""
    import steelbuild
    _spend()
    Cut, Common, Fuse = _ocp()
    op = {'cut': Cut, 'common': Common, 'fuse': Fuse}[kind]()
    args, tools = steelbuild._shape_list(), steelbuild._shape_list()
    args.Append(copy_shape(a))
    tools.Append(copy_shape(b))
    op.SetArguments(args)
    op.SetTools(tools)
    op.SetFuzzyValue(fuzzy)
    op.SetNonDestructive(True)
    op.Build()
    if not op.IsDone():
        return None
    return op.Shape()


def solids_of(shape):
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID
    out = []
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        out.append(ex.Current())
        ex.Next()
    return out


def moved(shape, off):
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(*off))
    return shape.Moved(TopLoc_Location(t))


def bbox(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, b, False, False)
    p, q = b.CornerMin(), b.CornerMax()
    return np.array([p.X(), p.Y(), p.Z()]), np.array([q.X(), q.Y(), q.Z()])


def is_valid(shape):
    from OCP.BRepCheck import BRepCheck_Analyzer
    return BRepCheck_Analyzer(shape).IsValid()


def occ_faces(shape):
    """polygon faces of a polyhedral OpenCASCADE shape: [[outer loop, hole loops ...], ...] wound about the outward
    normal (outer counter-clockwise)"""
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_WIRE
    from OCP.TopoDS import TopoDS
    from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
    from OCP.BRep import BRep_Tool
    from OCP.BRepGProp import BRepGProp_Face
    from OCP.gp import gp_Pnt, gp_Vec
    out = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current()) if hasattr(TopoDS, 'Face_s') else TopoDS.Face(ex.Current())
        ow = BRepTools.OuterWire_s(f)
        wires = [ow]
        exw = TopExp_Explorer(f, TopAbs_WIRE)
        while exw.More():
            w = TopoDS.Wire_s(exw.Current()) if hasattr(TopoDS, 'Wire_s') else TopoDS.Wire(exw.Current())
            if not w.IsSame(ow):
                wires.append(w)
            exw.Next()
        loops = []
        for w in wires:
            pts = []
            we = BRepTools_WireExplorer(w, f)
            while we.More():
                p = BRep_Tool.Pnt_s(we.CurrentVertex())
                pts.append((p.X(), p.Y(), p.Z()))
                we.Next()
            if len(pts) >= 3:
                loops.append(np.array(pts))
        if loops:
            # outward normal of the face (orientation applied) at its parametric centre
            gf = BRepGProp_Face(f)
            u0, u1, v0, v1 = gf.Bounds()
            p, nv = gp_Pnt(), gp_Vec()
            gf.Normal((u0 + u1) / 2, (v0 + v1) / 2, p, nv)
            nn = np.array([nv.X(), nv.Y(), nv.Z()])
            if np.dot(newell(loops[0]), nn) < 0:
                loops = [lp[::-1] for lp in loops]
            out.append(loops)
        ex.Next()
    return out


def face2d(outer, holes=()):
    """planar face in the XY plane from 2D loops"""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Pnt

    def wire(lp):
        mp = BRepBuilderAPI_MakePolygon()
        for x, y in lp:
            mp.Add(gp_Pnt(float(x), float(y), 0.0))
        mp.Close()
        return mp.Wire()
    mf = BRepBuilderAPI_MakeFace(wire(outer if area2(np.asarray(outer)) > 0 else np.asarray(outer)[::-1]), True)
    for h in holes:
        h = np.asarray(h)
        mf.Add(wire(h if area2(h) < 0 else h[::-1]))
    if not mf.IsDone():
        return None
    from OCP.ShapeFix import ShapeFix_Face
    fx = ShapeFix_Face(mf.Face())
    fx.Perform()
    return fx.Face()


def union2d(polys):
    """union of 2D polygons (each (outer, holes)) -> [(outer, [holes])] regions, loops as 2D vertex arrays. One boolean
    of all polygons builds the arrangement of all their edges: for the 300 - 2,000 overlapping, nearly edge-on facet
    projections of a large curved faceted solid it took up to 430 s and grew past 7 GB (where the search hung); within
    MAX_FACES (every search input, the tools included, is a solid of at most MAX_FACES faces) it stayed under 2 GB and
    31 s on every part of the 33 models"""
    import steelbuild
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    _spend()
    faces = [f for f in (face2d(o, h) for o, h in polys) if f is not None]
    if not faces:
        return []
    if len(faces) == 1:
        shape = faces[0]
    else:
        op = BRepAlgoAPI_Fuse()
        args, tools = steelbuild._shape_list(), steelbuild._shape_list()
        args.Append(faces[0])
        for f in faces[1:]:
            tools.Append(f)
        op.SetArguments(args)
        op.SetTools(tools)
        op.SetFuzzyValue(1e-6)
        op.Build()
        if not op.IsDone():
            return None
        shape = op.Shape()
    us = ShapeUpgrade_UnifySameDomain(shape, True, True, False)
    us.Build()
    shape = us.Shape()
    regions = []
    for loops in occ_faces(shape):
        lps = [simplify2(lp[:, :2], 1e-7) for lp in loops]
        if abs(area2(lps[0])) < 1e-9:
            continue
        regions.append((lps[0], lps[1:]))
    return regions


# ======================================================================================== descriptions -> solids
def _seg(p):
    pts = [[round(float(x), 6), round(float(y), 6)] for x, y in p]
    return [{'t': 'L', 'p': pts + [pts[0]]}]


def _clean2(p):
    """2D loop as written to the schedule (6 decimals), without repeated or collinear points; None if degenerate"""
    q = np.round(np.asarray(p, float), 6)
    q = simplify2(q, 1e-7)
    if len(q) < 3 or abs(area2(q)) < 1e-6:
        return None
    return q


def build_descs(descs, pid='_part'):
    """build body descriptions exactly as build_model.py would (recover.emit rows -> steelbuild.build_part)"""
    import recover
    return recover.build_candidates(pid, descs)


def search_build(descs):
    """build_descs for a trial construction of the search (counted against MAX_OPS)"""
    _spend()
    return build_descs(descs)


# ======================================================================================== comparison
# Booleans between solids whose faces coincide (a rebuilt part and its source) are ill-conditioned in OpenCASCADE: the
# same pair can come out right, or as 'disjoint', depending on fuzzy value and placement. Every measurement below is
# therefore repeated in a fixed list of frames (placement around the solid's own rounded centre, optionally turned by a
# fixed rotation) and fuzzy values, and the first SOUND result is used: volumes that add up and a common part that is
# not empty. The list is fixed, so the outcome is deterministic.
MEASURE_FRAMES = (None, ((0.267261241912, 0.534522483825, 0.801783725737), 0.7),
                  ((0.801783725737, -0.267261241912, 0.534522483825), 1.9))
MEASURE_FUZZY = (1e-3, 1e-2, 0.0)


def _trsf(off, rot):
    from OCP.gp import gp_Trsf, gp_Vec, gp_Ax1, gp_Pnt, gp_Dir
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(*[float(x) for x in off]))
    if rot:
        r = gp_Trsf()
        r.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(*rot[0])), rot[1])
        t = r.Multiplied(t)
    return t


def _xf(shape, t):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


def _configs():
    for rot in MEASURE_FRAMES:
        for fz in MEASURE_FUZZY:
            yield rot, fz


def search_coincide(B, Pshape, vB=None):
    """search only (the acceptance is recover.coincide): does the rebuilt shape coincide with the source shape?
    1. valid solids, same count, volume within SEARCH_SYMDIFF, bounding box within SEARCH_BBOX (exact, no booleans)
    2. the two surfaces lie within SEARCH_BBOX of each other, same outward side, at points sampled on every face of
       both (boolean-free; local: a feature the rebuilt part lacks or adds is found however small its volume)
    3. symmetric difference within SEARCH_SYMDIFF: the first sound boolean measurement (see MEASURE_FRAMES); when none
       is sound, step 2 bounds it by SEARCH_BBOX x surface area, accepted only if that bound is within SEARCH_SYMDIFF"""
    nb, nP = len(solids_of(B)), len(solids_of(Pshape))
    if nP != nb or nP == 0:
        return False, {'why': f'{nP} solids'}
    if not all(is_valid(x) for x in solids_of(Pshape)):
        return False, {'why': 'invalid solid'}
    P = Pshape
    lo, hi = bbox(B)
    c0 = -np.round((lo + hi) / 2)
    vB = volume(B) if vB is None else vB
    vP = volume(P)
    plo, phi = bbox(P)
    dbb = float(max(np.max(np.abs(plo - lo)), np.max(np.abs(phi - hi))))
    info = {'vol_rel': abs(vP - vB) / vB if vB > 0 else 1.0, 'bbox_mm': dbb}
    if vB <= 0 or abs(vP - vB) > SEARCH_SYMDIFF * vB:
        info['why'] = 'volume'
        return False, info
    if dbb > SEARCH_BBOX:
        info['why'] = 'bbox'
        return False, info
    n, bad = side_test(B, P, SEARCH_BBOX)
    info.update(surface_points=n, surface_off=bad)
    if bad or n == 0:
        info['why'] = 'surfaces differ at %d of %d points' % (bad, n)
        return False, info
    area = _surface_area(B)
    meas = None
    for rot, fz in _configs():
        t = _trsf(c0, rot)
        Bl, Pl = _xf(B, t), _xf(P, t)
        tol = max(1e-4 * vB, 2 * fz * area)
        # sound: min(d1, d2, c) >= -1e-6 vB, c >= half the smaller volume, d1 + c = vB and d2 + c = vP within tol;
        # tested boolean by boolean (common, then each cut), the next boolean only while the test holds (independent
        # booleans: the same test, fewer booleans when it fails)
        r3 = bop('common', Bl, Pl, fz)
        if r3 is None:
            continue
        c = volume(r3)
        if c < -1e-6 * vB or c < 0.5 * min(vB, vP):
            continue
        r1 = bop('cut', Bl, Pl, fz)
        if r1 is None:
            continue
        d1 = volume(r1)
        if d1 < -1e-6 * vB or abs(d1 + c - vB) > tol:
            continue
        r2 = bop('cut', Pl, Bl, fz)
        if r2 is None:
            continue
        d2 = volume(r2)
        sound = d2 >= -1e-6 * vB and abs(d2 + c - vP) <= tol
        if sound:
            meas = ((d1 + d2) / vB, c / vB, fz, 0 if rot is None else MEASURE_FRAMES.index(rot))
            break
    if meas is not None:
        info.update(symdiff_rel=meas[0], common_rel=meas[1], fuzzy=meas[2], frame=meas[3])
        if meas[0] > SEARCH_SYMDIFF:
            info['why'] = 'symdiff %.2e' % meas[0]
            return False, info
        return True, info
    bound = SEARCH_BBOX * area / vB
    info['symdiff_bound'] = bound
    if bound > SEARCH_SYMDIFF:
        info['why'] = 'compare failed'
        _dump(B, P)
        return False, info
    return True, info


def _dump(B, P):
    if os.environ.get('RECOVER_CUTS_DUMP'):
        from OCP.BRepTools import BRepTools
        d = os.environ['RECOVER_CUTS_DUMP']
        k = len([f for f in os.listdir(d) if f.endswith('_B.brep')])
        BRepTools.Write_s(B, os.path.join(d, f'{k}_B.brep'))
        BRepTools.Write_s(P, os.path.join(d, f'{k}_P.brep'))


def _face_samples(shape, delta, cap):
    """points on the faces of a polyhedral solid (triangle centres at least 2 delta inside their face) and the outward
    normals there"""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopoDS import TopoDS
    from OCP.BRep import BRep_Tool
    from OCP.TopLoc import TopLoc_Location
    s = copy_shape(shape)
    BRepMesh_IncrementalMesh(s, 0.5, False, 0.5, True)
    lo, hi = bbox(s)
    h = max(5.0, float(np.linalg.norm(hi - lo)) / 60.0)
    pts, nrm = [], []
    ex = TopExp_Explorer(s, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current()) if hasattr(TopoDS, 'Face_s') else TopoDS.Face(ex.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(f, loc)
        ex.Next()
        if tri is None:
            continue
        tr = loc.Transformation()
        V = []
        for i in range(1, tri.NbNodes() + 1):
            q = tri.Node(i).Transformed(tr)
            V.append((q.X(), q.Y(), q.Z()))
        V = np.array(V)
        T = np.array([tri.Triangle(i).Get() for i in range(1, tri.NbTriangles() + 1)]) - 1
        if not len(T):
            continue
        a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
        # boundary of the face = mesh edges used by one triangle only (before refinement)
        E = np.sort(np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), axis=1)
        u_, cnt = np.unique(E, axis=0, return_counts=True)
        bd = u_[cnt == 1]
        p0, p1 = V[bd[:, 0]], V[bd[:, 1]]
        # refine: split triangles at edge midpoints until no edge is longer than h (bounded)
        for _ in range(6):
            el = np.max(np.stack([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)]), 0)
            big = el > h
            if not big.any() or len(a) > 4 * cap:
                break
            ab, bc, ca = (a[big] + b[big]) / 2, (b[big] + c[big]) / 2, (c[big] + a[big]) / 2
            a = np.concatenate([a[~big], a[big], ab, ca, ab])
            b, c = (np.concatenate([b[~big], ab, b[big], bc, bc]), np.concatenate([c[~big], ca, bc, c[big], ca]))
        n = np.cross(b - a, c - a)
        ln = np.linalg.norm(n, axis=1)
        ok = ln > 1e-12
        if not ok.any():
            continue
        fn = n[ok].sum(0)
        fn /= max(np.linalg.norm(fn), 1e-30)
        if f.Orientation() == TopAbs_REVERSED:
            fn = -fn
        cen = (a + b + c)[ok] / 3.0
        e = p1 - p0
        L2 = np.maximum(np.einsum('ij,ij->i', e, e), 1e-30)
        dmin = np.full(len(cen), np.inf)
        for k in range(0, len(p0), 256):
            q0, ee, ll = p0[k:k + 256], e[k:k + 256], L2[k:k + 256]
            w = cen[:, None, :] - q0[None]
            tt = np.clip(np.einsum('ijk,jk->ij', w, ee) / ll[None], 0, 1)
            dd = np.linalg.norm(w - tt[..., None] * ee[None], axis=2)
            dmin = np.minimum(dmin, dd.min(1))
        keep = cen[dmin >= 2 * delta]
        pts.append(keep)
        nrm.append(np.repeat(fn[None], len(keep), 0))
    if not pts:
        return np.zeros((0, 3)), np.zeros((0, 3))
    # every face keeps samples: an equal share of the budget first, the rest in proportion (deterministic thinning)
    sizes = np.array([len(x) for x in pts])
    if sizes.sum() > cap:
        share = np.minimum(sizes, max(1, cap // (2 * len(sizes))))
        rest = cap - share.sum()
        if rest > 0:
            extra = sizes - share
            share = share + np.floor(extra * rest / max(extra.sum(), 1)).astype(int)
        for k in range(len(pts)):
            if share[k] < sizes[k]:
                idx = np.linspace(0, sizes[k] - 1, max(share[k], 0)).round().astype(int)
                pts[k], nrm[k] = pts[k][idx], nrm[k][idx]
    return np.concatenate(pts), np.concatenate(nrm)


class _FaceSet:
    """planar polygon faces of a solid with their planes and 2D frames, for point-to-surface tests"""

    def __init__(self, shape):
        self.faces = []
        for loops in occ_faces(shape):
            nv = newell(loops[0])
            for h in loops[1:]:
                nv = nv + newell(h)
            ln = np.linalg.norm(nv)
            if ln < 1e-12:
                continue
            n = nv / ln
            c = loops[0].mean(0)
            u = loops[0][1] - loops[0][0]
            u = u - n * (u @ n)
            if np.linalg.norm(u) < 1e-12:
                continue
            u /= np.linalg.norm(u)
            v = np.cross(n, u)
            loops2 = [np.stack([(lp - c) @ u, (lp - c) @ v], 1) for lp in loops]
            self.faces.append((n, float(n @ c), c, u, v, loops2))
        self.N = np.array([f[0] for f in self.faces]) if self.faces else np.zeros((0, 3))
        self.D = np.array([f[1] for f in self.faces]) if self.faces else np.zeros(0)


def surface_test(pts, nrm, target, delta):
    """for each sample point (on a face of one solid, with that face's outward normal): is there a face of the other
    solid facing the same way (within 10 degrees) whose plane is within delta and which contains the point's projection
    (or comes within delta of it)? -> number of points without such a face"""
    if not len(pts):
        return 0
    if not len(target.faces):
        return len(pts)
    ok = np.zeros(len(pts), bool)
    cos_tol = math.cos(math.radians(10.0))
    for k0 in range(0, len(pts), 1024):
        P_, N_ = pts[k0:k0 + 1024], nrm[k0:k0 + 1024]
        dist = np.abs(P_ @ target.N.T - target.D[None])           # points x faces
        same = (N_ @ target.N.T) >= cos_tol
        cand = (dist <= delta) & same
        for j in np.nonzero(cand.any(0))[0]:
            idx = np.nonzero(cand[:, j] & ~ok[k0:k0 + 1024])[0]
            if not len(idx):
                continue
            n, d, c, u, v, loops2 = target.faces[j]
            q = np.stack([(P_[idx] - c) @ u, (P_[idx] - c) @ v], 1)
            ins = _inside(q, loops2[0])
            for h in loops2[1:]:
                ins &= ~_inside(q, h)
            near = ~ins
            if near.any():
                dmin = np.min([_seg_dist(q[near], lp) for lp in loops2], axis=0)
                ins[np.nonzero(near)[0]] = dmin <= delta
            ok[k0 + idx[ins]] = True
    return int((~ok).sum())


def side_test(B, P, delta, cap=3000):
    """boolean-free coincidence test: the two surfaces lie within delta of each other, with the same outward side,
    at points sampled on every face of both solids -> (number of points, number of points off the other surface)"""
    n = bad = 0
    FB, FP = _FaceSet(B), _FaceSet(P)
    for S, T in ((B, FP), (P, FB)):
        pts, nrm = _face_samples(S, delta, cap)
        n += len(pts)
        bad += surface_test(pts, nrm, T, delta)
    return n, bad


# ======================================================================================== the search
class _Fail(Exception):
    pass


def section_desc(o0, u, v, a, L, outer, holes):
    """prism description from a 2D section (outer + holes, exact source vertices) in the frame (o0; u, v), extruded
    by L along a"""
    outer = _clean2(outer)
    if outer is None:
        raise _Fail('section degenerate')
    holes = [h for h in (_clean2(h) for h in holes) if h is not None]
    return dict(o=[float(x) for x in o0], x=[float(x) for x in u], z=[float(x) for x in a], vec=[float(x) for x in a * L],
                cuts=[], tools=[], profile=None, outline={'outer': _seg(outer), 'inner': [_seg(h) for h in holes]},
                _sec=(outer, holes))


def regularize(d):
    """sections that are regular N-gons (faceted round bars, studs, holes) written as NGON profiles (sides, radius)
    instead of vertex lists, recursively; the caller re-checks the rebuilt part and keeps the vertex lists otherwise"""
    import recover
    e = dict(d)
    outer, holes = d['_sec']
    ng = recover.regular_polygon(outer, holes)
    if ng:
        e['profile'] = dict(kind='NGON', **ng)
        e['outline'] = None
    e['tools'] = [regularize(t) for t in d.get('tools', [])]
    return e


def strip(d):
    e = {k: v for k, v in d.items() if not k.startswith('_')}
    e['tools'] = [strip(t) for t in d.get('tools', [])]
    return e


def _sliver(outer, holes=()):
    """a region or hole only a facet twist wide (area / perimeter below 0.005 mm): source-grid noise"""
    p = np.asarray(outer)
    per = float(np.sum(np.linalg.norm(np.roll(p, -1, 0) - p, axis=1)))
    return abs(area2(p)) < 0.005 * per


def _seg_dist(pts, poly):
    """distance of 2D points to the boundary of a closed polygon"""
    a = np.asarray(poly)
    b = np.roll(a, -1, 0)
    d = np.full(len(pts), np.inf)
    for p0, p1 in zip(a, b):
        e = p1 - p0
        L2 = max(float(e @ e), 1e-30)
        t = np.clip(((pts - p0) @ e) / L2, 0.0, 1.0)
        q = p0 + t[:, None] * e
        d = np.minimum(d, np.linalg.norm(pts - q, axis=1))
    return d


def _inside(pts, poly):
    """even-odd point in polygon for many 2D points"""
    a = np.asarray(poly)
    b = np.roll(a, -1, 0)
    x, y = pts[:, 0], pts[:, 1]
    ins = np.zeros(len(pts), bool)
    for (x1, y1), (x2, y2) in zip(a, b):
        if y1 == y2:
            continue
        c = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1)
        ins ^= c
    return ins


def _shadow(poly, a, o0, u, v, thr):
    polys = []
    for i in range(len(poly.faces)):
        na = poly.N[i] @ a
        if na <= thr or poly.A[i] * na <= 1e-8:
            continue
        lps = [np.stack([(lp - o0) @ u, (lp - o0) @ v], 1) for lp in poly.faces[i]]
        if abs(area2(lps[0])) < 1e-8:
            continue
        polys.append((lps[0], lps[1:]))
    if not polys:
        return None
    regions = union2d(polys)
    if not regions:
        return None
    regions = [(o, [h for h in hs if not _sliver(h)]) for o, hs in regions if not _sliver(o)]
    if len(regions) > 1:
        big = max(abs(area2(r[0])) for r in regions)
        regions = [r for r in regions if abs(area2(r[0])) >= min(1e-4 * big, 1.0)]
    return regions


def envelope(poly, a):
    """envelope prism of the polyhedron along a: frame, t range and the section = union of the projections of the faces
    facing +a (for a closed polyhedron they cover its whole shadow) -> (o0, u, v, L, tmin, tmax, outer, holes)
    First the end faces proper (|n.a| > LAT_TOL): their union is the section if every vertex of the solid projects into
    it (within SUPPORT_TOL - side facets twisted by the source's 0.01 mm grid would only add slivers); else every face
    facing +a however slightly (a tapered side widens the shadow)."""
    u, v = frame_for(poly, a)
    o = poly.P.mean(0)
    tt = (poly.P - o) @ a
    tmin, tmax = float(tt.min()), float(tt.max())
    L = tmax - tmin
    if L <= 1e-6:
        raise _Fail('flat')
    o0 = o + tmin * a
    P2 = np.stack([(poly.P - o0) @ u, (poly.P - o0) @ v], 1)
    why = 'no end faces'
    for thr in (LAT_TOL, 1e-7):
        regions = _shadow(poly, a, o0, u, v, thr)
        if regions is None:
            why = 'envelope union failed'
            continue
        if len(regions) != 1:
            why = 'section in several pieces'
            continue
        outer, holes = regions[0]
        if len(outer) < 3:
            why = 'no section'
            continue
        ins = _inside(P2, outer)
        for h in holes:
            ins &= ~_inside(P2, h)
        out = ~ins
        if out.any():
            bd = [outer] + list(holes)
            dist = np.min([_seg_dist(P2[out], b) for b in bd], axis=0)
            if dist.max() > SUPPORT_TOL:
                why = 'section does not cover the solid'
                continue
        return o0, u, v, L, tmin, tmax, outer, holes
    raise _Fail(why)


def end_planes(poly, a, tmin, tmax, o, free=()):
    """distinct planes of the end faces (|n.a| >= LAT_TOL) that have the whole solid on their inner side; coplanar
    facets merge into one plane -> [{'p', 'n'}] with n the side kept. A plane square to the axis at the prism's own
    end (tmin, tmax: the prism's range along the axis from o) is the prism end itself, not a cut; so is one at a range
    end listed in `free` (a tool extended past that end through empty space)"""
    caps = [i for i in range(len(poly.faces)) if abs(poly.N[i] @ a) >= LAT_TOL]
    groups = []
    for i in sorted(caps, key=lambda i: (-poly.A[i], i)):
        n, c = poly.N[i], poly.C[i]
        for g in groups:
            if np.dot(n, g['n']) > 1 - 1e-6 and abs(np.dot(c - g['c'], g['n'])) < 1e-3:
                g['m'].append(i)
                break
        else:
            groups.append({'n': n, 'c': c, 'm': [i]})
    out = []
    for g in groups:
        n, c = g['n'], g['c']
        if np.max((poly.P - c) @ n) > SUPPORT_TOL:
            continue
        if abs(abs(n @ a) - 1) < 1e-6:
            t = (c - o) @ a
            if abs(t - tmin) < 0.02 or abs(t - tmax) < 0.02 or any(abs(t - f) < 0.02 for f in free):
                continue                      # the prism's own end
        out.append({'p': [round(float(x), 6) for x in c], 'n': [float(x) for x in -n]})
    if len(out) > MAX_CAP_PLANES:
        raise _Fail('too many end planes')
    out.sort(key=lambda q: (tuple(np.round(q['n'], 6)), tuple(q['p'])))
    return out


def _surface_area(shape):
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    g = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, g)
    return g.Mass()


def _centroid(shape):
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    c = g.CentreOfMass()
    return np.array([c.X(), c.Y(), c.Z()])


def cut_pieces(body, X, vX, region, root_vol):
    """connected pieces of (body - X) [inside region]: the material the body has in excess (X must lie inside the
    body); numerical slivers dropped; largest first. Measured in the fixed frames / fuzzy values until the volumes add
    up (see MEASURE_FRAMES)"""
    vb = volume(body)
    lo, hi = bbox(body)
    c0 = -np.round((lo + hi) / 2)
    for k, (rot, fz) in enumerate(_configs()):
        if k >= PIECE_TRIES:
            break
        t = _trsf(c0, rot)
        bl, Xl = _xf(body, t), _xf(X, t)
        # X must lie inside the body (up to the source grid) and the two differences must add up to the volumes; the
        # second boolean only when the first passes (the booleans are independent: the same test, fewer booleans)
        out = bop('cut', Xl, bl, fz)
        if out is None:
            continue
        vo = volume(out)
        if vo > PIECE_TOL * vX:
            _dbg('  pieces fz', fz, 'frame', rot is not None, 'vX', round(vX, 3), 'X-body', round(vo, 4))
            continue
        rem = bop('cut', bl, Xl, fz)
        if rem is None:
            continue
        vr = volume(rem)
        _dbg('  pieces fz', fz, 'frame', rot is not None, 'vX', round(vX, 3), 'vbody', round(vb, 3), 'X-body', round(vo, 4),
             'body-X', round(vr, 4))
        if abs((vr - vo) - (vb - vX)) > PIECE_TOL * vX:
            continue
        if region is not None and vr > 0:
            rem2 = bop('common', rem, _xf(region, t), fz)
            if rem2 is None or volume(rem2) > vr * (1 + 1e-6) + 1e-9:
                continue
            rem = rem2
        back = t.Inverted()
        pieces = []
        for p in solids_of(rem):
            vp = volume(p)
            if vp <= PIECE_MIN_REL * root_vol or 2 * vp / max(_surface_area(p), 1e-12) < PIECE_MIN_THICK:
                continue
            p = _xf(p, back)
            pieces.append((tuple(np.round(_centroid(p), 3)), round(vp, 3), p))
        pieces.sort(key=lambda x: (-x[1], x[0]))
        return [p for _, _, p in pieces]
    _UNSOUND[0] += 1
    if _UNSOUND[0] >= MAX_UNSOUND:
        _OPS[0] = MAX_OPS + 1                    # the search of this part ends here (every further operation fails)
        raise _Fail('search budget exceeded')
    raise _Fail('body does not contain the solid')


def solve(poly, shape, depth, root_vol, region=None):
    """description T (prism + end planes - tools) with T = shape; for a tool (region = the solid it is cut from) with
    region - T = region - shape: outside the region the tool may be larger, which keeps it simple and keeps its faces
    off the region's faces (a tool may then span the whole region along its axis, holes in its section may be filled)"""
    if len(poly.faces) > MAX_FACES:
        raise _Fail('too many faces')
    if depth > 0 and len(poly.faces) > MAX_TOOL_FACES:
        raise _Fail('cut-out too complex')
    axes = axis_candidates(poly, MAX_AXES[depth])
    if not axes:
        raise _Fail('no axis')
    target, rpts = None, None
    if region is not None:
        vX, vR = volume(shape), volume(region)
        lo, hi = bbox(region)
        c0 = -np.round((lo + hi) / 2)
        for rot, fz in _configs():
            t = _trsf(c0, rot)
            r = bop('cut', _xf(region, t), _xf(shape, t), fz)
            if r is not None and abs(volume(r) - (vR - vX)) <= 1e-4 * vR:
                target = _xf(r, t.Inverted())
                break
        if target is None:
            raise _Fail('cut-out not separable')
        rpts = np.concatenate([lp for fc in occ_faces(region) for lp in fc])
    variants = [(False, True), (False, False), (True, True), (True, False)] if region is not None else [(False, False)]
    first = None
    for a in axes:
        for filled, extended in variants:
            try:
                return solve_axis(poly, shape, a, depth, root_vol, region, filled, extended, target, rpts)
            except _Skip:
                continue
            except Exception as e:                     # _Fail, or a construction OpenCASCADE refuses
                _reraise_oom(e)
                why = str(e) if isinstance(e, _Fail) else f'error {type(e).__name__}'
                _dbg('  fail depth', depth, 'axis', np.round(a, 5), 'filled' if filled else 'exact', 'extended' if extended else 'own', why)
                first = first or why
    raise _Fail(first)


class _Skip(Exception):
    pass


def solve_axis(poly, shape, a, depth, root_vol, region, filled, extended, target, rpts):
    import steelbuild
    o0, u, v, L, tmin, tmax, outer, holes = envelope(poly, a)
    if filled:
        if not holes:
            raise _Skip()
        holes = []
    o = poly.P.mean(0)
    p0, p1 = tmin, tmax
    free = []
    if extended:
        # the tool runs through the whole solid it is cut from; where that extension meets no material of it, the
        # tool's own end there is no cut at all (a hole through a web runs on through the space between the flanges)
        rt = (rpts - o) @ a
        p0, p1 = min(tmin, float(rt.min())), max(tmax, float(rt.max()))
        if p0 > tmin - 1e-6 and p1 < tmax + 1e-6:
            raise _Skip()
        for q0, q1, end in ((p0, tmin, tmin), (tmax, p1, tmax)):
            if q1 - q0 <= 1e-6:
                continue
            ext = search_build([section_desc(o + q0 * a, u, v, a, q1 - q0, outer, holes)])
            hit = bop('common', ext[0].wrapped, region, MEASURE_FUZZY[0]) if len(ext) == 1 else None
            if hit is not None and volume(hit) <= PIECE_MIN_REL * root_vol:
                free.append(end)
    d = section_desc(o + p0 * a, u, v, a, p1 - p0, outer, holes)
    d['cuts'] = end_planes(poly, a, p0, p1, o, free)
    _dbg('depth', depth, 'axis', np.round(a, 5), 'filled' if filled else 'exact', 'extended' if extended else 'own', 'L',
         round(p1 - p0, 3), 'section', len(outer), [len(h) for h in holes], 'area', round(area2(outer), 3), 'planes',
         len(d['cuts']), 'faces', len(poly.faces))
    built = search_build([d])
    if len(built) != 1:
        raise _Fail('body not built')
    vS = volume(shape)
    pieces = cut_pieces(built[0].wrapped, shape, vS, region, root_vol)
    if len(pieces) > MAX_TOOLS:
        raise _Fail('too many cut-outs')
    if pieces and depth >= MAX_DEPTH:
        raise _Fail('not an extrusion')
    body_shape = built[0].wrapped
    for pc in pieces:
        d['tools'].append(solve(Poly(occ_faces(pc)), pc, depth + 1, root_vol, body_shape))
    if d['tools']:
        built = search_build([d])
    if region is None:
        ok, info = search_coincide(shape, built[0].wrapped, vS)
    else:
        # the tool is judged by what it leaves of the solid it is cut from, cut exactly as steelbuild cuts
        from build123d import Solid, Compound
        res = steelbuild._cut(Solid(region) if region.ShapeType().name == 'TopAbs_SOLID' else Compound(region), built[0])
        ok, info = search_coincide(target, res.wrapped)
    _dbg('  check depth', depth, 'tools', len(d['tools']), ok, info)
    if not ok:
        raise _Fail('not an extrusion (%s)' % info.get('why'))
    return d


def translate(d, off):
    """description moved by the integer offset off (local search frame -> model coordinates)"""
    e = dict(d)
    e['o'] = [float(x + y) for x, y in zip(d['o'], off)]
    e['cuts'] = [{'p': [round(float(x + y), 6) for x, y in zip(c['p'], off)], 'n': c['n']} for c in d['cuts']]
    e['tools'] = [translate(t, off) for t in d.get('tools', [])]
    return e


def count_tools(d):
    return sum(1 + count_tools(t) for t in d.get('tools', []))


def try_cut_tools(rec):
    """one exact_geometry.jsonl record -> ([description per source solid], 'ok') or (None, reason)"""
    import steelbuild
    _OPS[0] = 0
    _UNSOUND[0] = 0
    # the first solid's own limits before its faces are sewn (seconds for a solid of 15,000 faces): the same answer the
    # loop below gives for it
    so0 = rec['solids'][0] if rec.get('solids') else None
    if so0 is not None and so0.get('voids'):
        return None, 'voids'
    if so0 is not None and len(so0['faces']) > MAX_FACES:
        return None, 'too many faces'
    try:
        Bs = steelbuild.exact_part(rec)
    except Exception as e:
        _reraise_oom(e)
        return None, 'source solid not valid'
    if len(Bs) != len(rec['solids']) or not all(B.is_valid for B in Bs):
        return None, 'source solid not valid'
    descs = []
    for so, B in zip(rec['solids'], Bs):
        if so.get('voids'):
            return None, 'voids'
        if len(so['faces']) > MAX_FACES:
            return None, 'too many faces'
        # search around the solid's own rounded centre (models sit far from the origin)
        allp = np.concatenate([np.asarray(lp, float) for fc in so['faces'] for lp in fc])
        off = np.round(allp.mean(0))
        local = [[(np.asarray(lp, float) - off).tolist() for lp in fc] for fc in so['faces']]
        poly = Poly(local)
        Bl = steelbuild.exact_part({'solids': [{'faces': local}]})
        if len(Bl) != 1 or not Bl[0].is_valid:
            return None, 'source solid not valid'
        try:
            d = solve(poly, Bl[0].wrapped, 0, volume(Bl[0].wrapped))
        except _Fail as e:
            return None, 'search budget exceeded' if _OPS[0] > MAX_OPS else str(e)
        descs.append(translate(d, off))
    # the part exactly as build_model.py builds it from the schedules, against the source solids: first with regular
    # polygon sections written as NGON profiles, else with the exact vertex lists. A construction with cut tools must
    # also give the same solid when the whole part is moved by small odd offsets (other float rounding, as on another
    # machine): booleans of coincident faces that only work by luck are rejected
    last = None
    for variant in ([regularize(d) for d in descs], descs):
        ok, checks, last = _check_part(variant, Bs)
        _dbg('final', 'ngon' if variant is not descs else 'exact', ok, last, checks)
        if not ok:
            continue
        if any(d.get('tools') for d in variant):
            for sh in STABILITY_SHIFTS:
                moved_src = [steelbuild.exact_part({'solids': [{'faces': [[(np.asarray(lp, float) + sh).tolist() for lp in fc]
                                                                          for fc in so['faces']]}]})[0] for so in rec['solids']]
                ok2, _, why2 = _check_part([translate(d, sh) for d in variant], moved_src)
                if not ok2:
                    ok, last = False, 'unstable construction (%s)' % why2
                    break
        if ok:
            out = [strip(d) for d in variant]
            for d, c in zip(out, checks):
                d['check'] = c
            return out, 'ok'
    return None, last


STABILITY_SHIFTS = ((0.1, 0.2, 0.3), (-0.37, 0.11, 0.73))


def _check_part(descs, Bs):
    """the acceptance: every solid rebuilt from the schedule rows passes recover.coincide against its source solid"""
    import recover
    built = build_descs(descs)
    if len(built) != len(Bs):
        return False, None, 'rebuilt part has %d solids' % len(built)
    checks = []
    for B, s in zip(Bs, built):
        ok, info = recover.coincide(B, s)
        if not ok:
            return False, None, 'rebuilt part differs (%s)' % info.get('reason')
        checks.append(info)
    return True, checks, None
