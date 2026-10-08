#!/usr/bin/env python3
"""Recover parameters for parts the source defines only as faceted surfaces.

A faceted part is accepted as `recovered` when it is a straight extrusion: its side faces are parallel to one axis, its
cross-section is the same along that axis, and its ends are planes. It is then rewritten as
    cross-section polygon (exact source vertices)  x  axis  x  length  -  end-plane cuts
and the rebuilt solid must coincide with the source solid: the two may differ only by the source's 0.01 mm coordinate
grid (every vertex of either within 0.05 mm of the other's surface, symmetric difference volume / surface area
<= 0.005 mm, centroid within what such a deviation can explain, bounding box within 0.05 mm).

A part that fails this test is tried by two fallbacks, in this order, each judged by the same criteria and limits
(coincide(), on the solid steelbuild rebuilds from the candidate's schedule rows, plus stricter checks of its own):
  sweep      (recover_sweep.py) a polygon section swept along a polyline: bent anchor rods and bars, hand rails, welds
             along edges or all round, studs and bolts (the section at several sizes along a straight path), and
             one-segment tubes (straight prisms the straight test mis-measured); written as profile + path (paths.json)
  cut tools  (recover_cuts.py) a straight extrusion modified by cut-outs the end planes cannot express (copes, notches,
             holes across the axis, many end facets): body prism - plane cuts - cut-tool prisms (solids.csv role
             cut_tool, cuts.csv kind 'solid' naming the tool in tool_solid_id), each tool again recovered the same way
Anything else (twisted or curved parts, parts whose rebuild does not coincide) stays `exact`.

Every candidate must also pass, as rebuilt from its schedule rows (exactly what build_model.py builds), the checks
verify.py will apply to it - the same rule, run through verify.check on verify.py's own references, with every limit
times VERIFY_MARGIN: the source check against the IFC (the authoritative geometry: the IfcOpenShell kernel's solids, or
a faceted source's faces sewn into solids; TOL_GRID_* limits) and the delivered check against the delivered STEP (with
the delivered file's own deviation from a closed source allowed). The references are verify.py's (verify.source_props,
verify.delivered_props) when recover.py is given --ifc and --step; without them the record's own faces stand in: faces
taken from the IFC at full precision (exact_sources.csv faces_source 'ifc') as the source, faces taken from the delivered
STEP as the delivered part. Coinciding with the record's faces is not enough on a 35 m thin-walled purlin, whose centroid
a 0.002 mm difference in wall thickness along its length moves by several mm (seen in giorgi cf82516f: 11 parts the v7
run delivered exact and verified, recovered by the fallbacks 1.0 - 8.7 mm off the delivered centroid). A fallback
result that fails is rejected and the part stays exact (reason in recover_log.jsonl); a straight extrusion that fails
while the part rebuilt from its exact faces passes is not taken either. Two further rules:
  * faces taken from the IFC at full precision carry no grid noise to absorb: for them the bounding box and vertex gap
    limits of the coincidence tests (ACCEPT_BBOX, ACCEPT_GAP) are at most verify.TOL_GRID_BBOX (0.02 mm);
  * a fallback result is accepted only if the STEP file steelbuild.write_step writes of it, read back, reproduces it
    (roundtrip_check: the same bodies, every solid valid and closed, volume within 1e-5 and centre within 0.005 mm).

Every part is processed in a worker process of its own budget (the part, not the model, is the unit of isolation):
  * time: --time-budget seconds per part (default TIME_BUDGET_S), enforced by the parent, which kills the worker;
  * memory: --mem-budget-gb per worker (default MEM_BUDGET_GB, at most 80 % of the machine's memory / jobs), enforced
    by the parent's watchdog on the worker's resident size (the worker is killed), and as a backstop for allocations
    faster than the watchdog by RLIMIT_DATA in the worker at twice the budget (an allocation beyond it fails);
  * a worker that dies (native fault) costs only the part it was on.
Such a part stays exact; recover_log.jsonl records the stage it was in and why ('time budget exceeded', 'memory budget
exceeded', 'native crash'), and the parts already finished are never run again. The budgets are a safety net: the
searches are bounded by counts (faces, axes, tools, operations), never by time, so the result is deterministic as long
as no part comes near a budget - recover_timing.json reports the slowest and largest parts against the budgets.

usage: recover.py SCHEDULE_DIR [--jobs N] [--fallbacks "sweep,cut tools"] [--time-budget S] [--mem-budget-gb G]
                               [--ifc SOURCE.ifc] [--step DELIVERED.step]
                               (--fallbacks "": the straight test only; --ifc / --step: verify.py's own references for
                               the acceptance, see above)
writes parts / profiles / profile_outlines / solids / cuts / exact_geometry back, paths.json (when any solid is swept),
recover_summary.json (parts per outcome: 'recovered' = straight test, 'recovered (<fallback>)', else the straight
test's reason), recover_fallbacks_summary.json (why each fallback rejected the parts it tried), recover_log.jsonl
(one line per faceted part: result, method, reasons, acceptance values) and recover_timing.json (run time, budgets,
slowest parts, isolated parts; the only output that differs from run to run). While it runs, recover_progress.json
lists the parts in flight (stage, seconds, resident MB).
"""
import argparse, csv, json, math, os, sys, collections, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'kit'))

LAT_TOL = 0.004          # |n . axis| below this: side face (0.23 deg; source vertices sit on a 0.01 mm grid)
# acceptance: the rebuilt extrusion may differ from the faceted source only by the source's 0.01 mm coordinate grid.
# A relative volume test (formerly symdiff <= 0.5 % of the volume) lets a large part hide a whole local feature: a 33 m
# wall whose end notch (4.7e6 mm3) was replaced by a full-width plane cut (23.6e6 mm3) passed at 5.9e-4 of its volume.
# The symmetric difference is therefore measured as a mean distance between the two surfaces (volume / surface area),
# which grid noise keeps far below 0.01 mm whatever the part size, and every vertex of either solid must also lie on
# the other's surface (rounding to the 0.01 mm grid moves a vertex up to 0.0087 mm and the rebuilt face through other
# rounded vertices as much again; 0.018 mm seen on a 21.8 m wall): a missed feature always leaves source vertices off
# the rebuilt surface, however small it is against the part (the notched walls: 278 mm). The centroid
# may move only as far as a surface deviation of ACCEPT_SYMDIFF_MM can move it (ACCEPT_SYMDIFF_MM * area * R / volume,
# R = half the bounding box diagonal): a fixed limit would reject long thin parts such as 4.5 m fillet welds of 11 mm2
# section, whose grid-rounded end sections differ by 0.2 % in area and put the faceted centroid 0.8 mm off mid-length
# while the exact IFC source is the straight prism the recovery rebuilds.
ACCEPT_GAP = 0.05           # mm: largest distance from a vertex of one solid to the surface of the other (both ways)
ACCEPT_SYMDIFF_MM = 0.005   # mm: symmetric difference volume / source surface area (mean distance of the surfaces)
ACCEPT_BBOX = 0.05          # mm
# the two limits above are those of faces on the delivered STEP's 0.01 mm grid; while a part is processed they hold the
# part's own limits (acceptance_limits: at most verify.TOL_GRID_BBOX for faces taken from the IFC at full precision)
ACCEPT_GAP_GRID, ACCEPT_BBOX_GRID = ACCEPT_GAP, ACCEPT_BBOX
AUDIT = False               # True: keep every candidate and record its check values (no acceptance test)
SRC_IFC = 'IFC faceted geometry, full precision'     # exact.py: the 'source' of a record whose faces come from the IFC


def vertex_gap(S, T):
    """largest distance from a vertex of solid S to the boundary surface of solid T (mm)"""
    from build123d import Compound
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    shells, verts = list(T.shells()), list(S.vertices())
    if not shells or not verts:
        return float('inf')
    surf = Compound(children=shells).wrapped
    worst = 0.0
    for v in verts:
        d = BRepExtrema_DistShapeShape(v.wrapped, surf)
        worst = max(worst, d.Value() if d.IsDone() else float('inf'))
    return worst


def newell(lp):
    p = np.asarray(lp)
    q = np.roll(p, -1, axis=0)
    n = np.array([np.sum((p[:, 1] - q[:, 1]) * (p[:, 2] + q[:, 2])), np.sum((p[:, 2] - q[:, 2]) * (p[:, 0] + q[:, 0])),
                  np.sum((p[:, 0] - q[:, 0]) * (p[:, 1] + q[:, 1]))])
    return n


def face_normal_area(fc):
    n = newell(fc[0])
    for h in fc[1:]:
        n = n + newell(h)            # holes are wound against the outer loop: their area subtracts
    a = np.linalg.norm(n) / 2.0
    return (n / (2 * a) if a > 0 else n), a


def find_axis(faces):
    na = [face_normal_area(fc) for fc in faces]
    N = np.array([x[0] for x in na])
    A = np.array([x[1] for x in na])
    order = np.argsort(-A)[:8]
    cands = []
    for i in range(len(order)):
        for j in range(i + 1, len(order)):
            c = np.cross(N[order[i]], N[order[j]])
            if np.linalg.norm(c) > 0.05:
                cands.append(c / np.linalg.norm(c))
    for i in order[:4]:
        cands.append(N[i] / max(np.linalg.norm(N[i]), 1e-12))
    best, bscore = None, None
    for a in cands:
        lat = np.abs(N @ a) < LAT_TOL * 5
        # natural extrusion axis: the fewest end faces (= fewest cuts), then the largest side area
        score = (-int((~lat).sum()), float(A[lat].sum()))
        if bscore is None or score > bscore:
            best, bscore = a, score
    if best is None:
        return None
    # refine: smallest eigenvector of the area-weighted normal scatter of the side faces
    lat = np.abs(N @ best) < LAT_TOL * 5
    S = (N[lat].T * A[lat]) @ N[lat]
    w, v = np.linalg.eigh(S)
    a = v[:, 0]
    if np.dot(a, best) < 0:
        a = -a
    return a, N, A


def section_loops(faces, o, a, t):
    """intersection of the polyhedron's faces with the plane {x : (x - o) . a = t} -> closed loops of 3D points"""
    segs = []
    for fc in faces:
        for lp in fc:
            P = np.asarray(lp)
            d = (P - o) @ a - t
            pts = []
            m = len(P)
            for i in range(m):
                d0, d1 = d[i], d[(i + 1) % m]
                if (d0 < 0) != (d1 < 0):
                    s = d0 / (d0 - d1)
                    pts.append(P[i] + s * (P[(i + 1) % m] - P[i]))
            if len(pts) % 2:
                return None
            # pair crossings along the face polygon trace (valid for faces cut once; multi-crossing faces are paired
            # by their order along the line)
            if len(pts) > 2:
                dirv = pts[1] - pts[0]
                pts.sort(key=lambda p: np.dot(p, dirv))
            for i in range(0, len(pts), 2):
                if np.linalg.norm(pts[i] - pts[i + 1]) > 1e-7:
                    segs.append((pts[i], pts[i + 1]))
    if not segs:
        return None
    # chain segments by shared end points
    key = lambda p: tuple(np.round(p, 5))
    adj = collections.defaultdict(list)
    for k, (p, q) in enumerate(segs):
        adj[key(p)].append((k, q))
        adj[key(q)].append((k, p))
    used = set()
    loops = []
    for k, (p, q) in enumerate(segs):
        if k in used:
            continue
        used.add(k)
        loop = [p, q]
        cur = q
        while True:
            nxt = [(kk, r) for kk, r in adj[key(cur)] if kk not in used]
            if not nxt:
                break
            kk, r = nxt[0]
            used.add(kk)
            if np.linalg.norm(r - loop[0]) < 1e-5:
                break
            loop.append(r)
            cur = r
        if np.linalg.norm(loop[-1] - loop[0]) < 1e-5:
            loop = loop[:-1]
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def to2d(loop, o, u, v):
    P = np.asarray(loop) - o
    return np.stack([P @ u, P @ v], 1)


def area2(p):
    return 0.5 * np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1])


def simplify(p, tol=1e-6):
    """drop collinear points (area tolerance), keep exact source vertices otherwise: repeatedly the first point (in
    loop order) collinear with its two neighbours is dropped. Removing point i changes the test only for its neighbours,
    so the scan resumes at i - 1 (at 0 when the last point went: point 0's previous neighbour changed) instead of
    restarting at 0 - the same points are dropped in the same order, in linear instead of quadratic time"""
    out = list(p)
    i = 0
    while len(out) > 3 and i < len(out):
        a, b, c = out[i - 1], out[i], out[(i + 1) % len(out)]
        if abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < tol * max(1.0, np.linalg.norm(c - a)):
            out.pop(i)
            i = 0 if i >= len(out) else max(i - 1, 0)
        else:
            i += 1
    return np.asarray(out)


def _inside(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def regular_polygon(outer, holes, tol=0.015):
    """an N-gon (N >= 6) with equal radii and equal edges (bolt shanks, round bars, rods, washers when one concentric
    regular hole) -> {sides, radius, pos_x, pos_y, pos_angle[, radius_inner]}; tol = the 0.01 mm grid of the faceted source"""
    def fit(p):
        n = len(p)
        if n < 6:
            return None
        c = p.mean(0)
        r = np.linalg.norm(p - c, axis=1)
        e = np.linalg.norm(np.roll(p, -1, 0) - p, axis=1)
        if r.max() - r.min() > tol or e.max() - e.min() > tol * 2:
            return None
        return n, c, float(r.mean()), math.atan2(p[0][1] - c[1], p[0][0] - c[0])
    f = fit(outer)
    if not f:
        return None
    n, c, R, ang = f
    out = dict(sides=n, radius=round(R, 6), pos_x=round(float(c[0]), 6), pos_y=round(float(c[1]), 6), pos_angle=round(ang, 9))
    if holes:
        if len(holes) != 1:
            return None
        g = fit(holes[0])
        if not g or g[0] != n or np.linalg.norm(g[1] - c) > tol:
            return None
        out['radius_inner'] = round(g[2], 6)
        out['angle_inner'] = round(g[3] - ang, 9)
    return out


def try_part(rec):
    """-> dict with profile outline, frame, vector, cuts  or  None"""
    import steelbuild
    from build123d import Vector
    out = []
    solids_exact = steelbuild.exact_part(rec)
    if len(solids_exact) != len(rec['solids']) or not all(B.is_valid for B in solids_exact):
        return None, 'source solid not valid'
    for so, B in zip(rec['solids'], solids_exact):
        if so.get('voids'):
            return None, 'voids'
        faces = [[np.asarray(lp, float) for lp in fc] for fc in so['faces']]
        r = find_axis(faces)
        if r is None:
            return None, 'no axis'
        a, N, A = r
        allp = np.concatenate([lp for fc in faces for lp in fc])
        o = allp.mean(0)
        tt = (allp - o) @ a
        tmin, tmax = tt.min(), tt.max()
        L = tmax - tmin
        if L <= 0:
            return None, 'flat'
        lat = np.abs(N @ a) < LAT_TOL
        caps = [i for i in range(len(faces)) if not lat[i]]
        if len(caps) > 12:
            return None, 'too many end faces'
        loops = section_loops(faces, o, a, tmin + 0.5003 * L)
        if not loops:
            return None, 'no section'
        # 2D frame: u along the projection of the largest side face, v = a x u
        big = int(np.argmax(np.where(lat, A, 0)))
        u = np.cross(N[big], a)
        u /= np.linalg.norm(u)
        v = np.cross(a, u)
        o0 = o + tmin * a
        L2 = [simplify(to2d(lp, o0, u, v)) for lp in loops]
        ar = [area2(p) for p in L2]
        k = int(np.argmax(np.abs(ar)))
        outer = L2[k]
        holes = [p for i, p in enumerate(L2) if i != k]
        n_outer_like = sum(1 for x in ar if abs(x) > 1e-9 and np.sign(x) == np.sign(ar[k]))
        if n_outer_like > 1:
            return None, 'section in several pieces'
        if any(not _inside(h.mean(0), outer) or abs(area2(h)) >= abs(ar[k]) for h in holes):
            return None, 'section in several pieces'
        seg = lambda p: [{'t': 'L', 'p': [[round(float(x), 6), round(float(y), 6)] for x, y in p] + [[round(float(p[0][0]), 6), round(float(p[0][1]), 6)]]}]
        outline = {'outer': seg(outer), 'inner': [seg(h) for h in holes]}
        cuts = []
        seen = []
        for i in caps:
            n = N[i]
            c = faces[i][0].mean(0)
            # end faces square to the axis at the extreme ends are the prism ends themselves
            if abs(abs(np.dot(n, a)) - 1) < 1e-6 and (abs((c - o) @ a - tmin) < 0.02 or abs((c - o) @ a - tmax) < 0.02):
                continue
            dup = any(np.dot(n, sn) > 1 - 1e-9 and abs(np.dot(c - sc, sn)) < 1e-4 for sn, sc in seen)
            if dup:
                continue
            seen.append((n, c))
            keep = -n
            cuts.append({'p': [round(float(x), 6) for x in c], 'n': [float(x) for x in keep]})
        cand = dict(profile=None, outline=outline, o=[float(x) for x in o0], x=[float(x) for x in u], z=[float(x) for x in a],
                    vec=[float(x) for x in a * L], cuts=cuts)
        # rebuild and compare with the source solid
        prof = {'kind': 'POLY', 'pos_x': 0, 'pos_y': 0, 'pos_angle': 0}
        ng = regular_polygon(outer, holes)
        if ng:
            prof = dict(kind='NGON', **ng)
            outline = None
        try:
            face = steelbuild.profile_face(prof, outline)
        except Exception as e:
            if is_oom(e):
                raise
            return None, 'section not a valid face'
        from build123d import Solid, Location, CenterOf
        from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
        from OCP.gp import gp_Vec
        pl = steelbuild._plane(cand['o'], cand['x'], cand['z'])
        P = Solid(BRepPrimAPI_MakePrism(face.moved(Location(pl)).wrapped, gp_Vec(*cand['vec'])).Shape())
        for c in cuts:
            P = steelbuild._keep_side(P, c['p'], c['n'])
        bb1, bb2 = B.bounding_box(), P.bounding_box()
        dbb = max(abs(bb1.min.X - bb2.min.X), abs(bb1.min.Y - bb2.min.Y), abs(bb1.min.Z - bb2.min.Z),
                  abs(bb1.max.X - bb2.max.X), abs(bb1.max.Y - bb2.max.Y), abs(bb1.max.Z - bb2.max.Z))
        if dbb > ACCEPT_BBOX and not AUDIT:
            # the bounding box alone rejects the candidate (the test below requires dbb <= ACCEPT_BBOX): the two
            # booleans are not run - on a faceted solid of thousands of faces they took up to 620 s, for the same answer
            return None, f'not an extrusion (bbox {dbb:.3f} mm; symmetric difference not measured)'
        try:
            vB, vP = B.volume, P.volume
            d1 = steelbuild._cut(B, P).volume
            d2 = steelbuild._cut(P, B).volume
        except Exception as e:
            if is_oom(e):
                raise
            return None, 'compare failed'
        aB = B.area
        dcen = (B.center(CenterOf.MASS) - P.center(CenterOf.MASS)).length
        sd_mm = (d1 + d2) / aB if aB > 0 else float('inf')
        cen_lim = ACCEPT_SYMDIFF_MM * aB * (bb1.diagonal / 2) / vB
        ok = sd_mm <= ACCEPT_SYMDIFF_MM and dcen <= cen_lim and dbb <= ACCEPT_BBOX
        gap = max(vertex_gap_fast(B, P), vertex_gap_fast(P, B)) if (ok or AUDIT) else float('nan')
        check = {'symdiff_rel': (d1 + d2) / vB, 'symdiff_mm': sd_mm, 'gap_mm': gap, 'centroid_mm': dcen,
                 'centroid_limit_mm': cen_lim, 'bbox_mm': dbb, 'vol_rel': abs(vP - vB) / vB}
        if not AUDIT and not (ok and gap <= ACCEPT_GAP):
            return None, (f'not an extrusion (symdiff {sd_mm:.2e} mm, centroid {dcen:.3f} of {cen_lim:.3f} mm, '
                          f'bbox {dbb:.3f}, vertex gap {gap:.3f} mm)')
        cand['profile'] = prof if prof['kind'] == 'NGON' else None
        cand['check'] = check
        out.append(cand)
    return out, 'ok'


# ======================================================================================== acceptance of the fallbacks
# The sweep (recover_sweep.py) and cut-tool (recover_cuts.py) fallbacks are judged by the same criteria as try_part,
# with the same limits: bounding box within ACCEPT_BBOX, centroid within the limit a surface deviation of
# ACCEPT_SYMDIFF_MM can explain, every vertex of either solid within ACCEPT_GAP of the other's surface, symmetric
# difference volume / source surface area <= ACCEPT_SYMDIFF_MM. Only the measurement of the symmetric difference is made
# robust: a boolean between two solids whose faces coincide up to the source's 0.01 mm grid is ill-conditioned in
# OpenCASCADE (for a 4.8 mm fillet weld rebuilt to 0.007 mm the cut returns the whole weld, or nothing, depending on the
# fuzzy value), so try_part rejects such parts on a wrong measurement - and a wrong measurement of zero would accept.
# Here the symmetric difference is measured twice and the larger value is the one tested:
#   * boolean-free: the distance from deterministic sample points on every triangle of each surface to the other
#     surface, integrated over the surface (for surfaces this close the integral is the symmetric difference volume);
#     its largest value is also tested against ACCEPT_GAP (a local test: a feature one solid lacks leaves sample points
#     off the other's surface however small it is against the part - a stricter test than try_part's)
#   * boolean: B - P, P - B and B & P in a fixed list of frames and fuzzy values, the first SOUND result (the three
#     volumes add up to both solids' volumes within a tenth of the acceptance) is used; when none is sound, only the
#     boolean-free measurement is available and the check records symdiff_method 'surface'.
# The list of frames is fixed and the sample points are deterministic, so the outcome is deterministic.
SOUND_FRAMES = (None, ((0.267261241912, 0.534522483825, 0.801783725737), 0.7),
                ((0.801783725737, -0.267261241912, 0.534522483825), 1.9))
SOUND_FUZZY = (1e-3, 0.0)        # never more than steelbuild's FUZZY: a larger fuzzy value merges real deviations away


def _triangles(shape):
    """triangles (n x 3 x 3) of a solid with planar faces (the triangulation of a planar face is exact: its nodes are
    the face's own vertices, whatever the deflection); a copy is meshed, the shape itself is not touched"""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.BRep import BRep_Tool
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    s = BRepBuilderAPI_Copy(shape.wrapped, True, False).Shape()
    BRepMesh_IncrementalMesh(s, 10.0, False, 0.5, False)
    face = TopoDS.Face_s if hasattr(TopoDS, 'Face_s') else TopoDS.Face
    out = []
    ex = TopExp_Explorer(s, TopAbs_FACE)
    while ex.More():
        loc = TopLoc_Location()
        T = BRep_Tool.Triangulation_s(face(ex.Current()), loc)
        if T is None:
            raise ValueError('face without triangulation')
        tr = loc.Transformation()
        nodes = np.array([(lambda q: (q.X(), q.Y(), q.Z()))(T.Node(i).Transformed(tr)) for i in range(1, T.NbNodes() + 1)])
        idx = np.array([T.Triangle(i).Get() for i in range(1, T.NbTriangles() + 1)], int) - 1
        if len(idx):
            out.append(nodes[idx])
        ex.Next()
    return np.concatenate(out) if out else np.zeros((0, 3, 3))


_BARY = {}


def _bary(k):
    """barycentric (u, v) of the centroids of the k*k sub-triangles of a triangle"""
    if k not in _BARY:
        uv = [((3 * i + 1) / (3 * k), (3 * j + 1) / (3 * k)) for i in range(k) for j in range(k - i)]
        uv += [((3 * i + 2) / (3 * k), (3 * j + 2) / (3 * k)) for i in range(k - 1) for j in range(k - 1 - i)]
        _BARY[k] = np.array(uv)
    return _BARY[k]


def _samples(T, n=4000):
    """deterministic sample points on a triangulated surface (every triangle at least one) and the area each stands for"""
    e1, e2 = T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]
    A = 0.5 * np.linalg.norm(np.cross(e1, e2), axis=1)
    a0 = max(A.sum() / n, 1e-12)
    P, W = [], []
    for t, a, u1, u2 in zip(T, A, e1, e2):
        if a <= 0:
            continue
        k = min(60, max(1, int(math.ceil(math.sqrt(a / a0)))))
        uv = _bary(k)
        P.append(t[0] + np.outer(uv[:, 0], u1) + np.outer(uv[:, 1], u2))
        W.append(np.full(len(uv), a / (k * k)))
    return (np.concatenate(P), np.concatenate(W)) if P else (np.zeros((0, 3)), np.zeros(0))


def _point_triangle(p, a, b, c):
    """distance from points p to triangles (a, b, c), row by row (closest point by Voronoi regions)"""
    dot = lambda x, y: np.einsum('ij,ij->i', x, y)
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = dot(ab, ap), dot(ac, ap)
    bp = p - b
    d3, d4 = dot(ab, bp), dot(ac, bp)
    cp = p - c
    d5, d6 = dot(ab, cp), dot(ac, cp)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    with np.errstate(divide='ignore', invalid='ignore'):
        den = 1.0 / (va + vb + vc)
        q = a + ab * (vb * den)[:, None] + ac * (vc * den)[:, None]                  # inside the face
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        m = (va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0)
        q = np.where(m[:, None], b + (c - b) * w[:, None], q)                        # edge bc
        w = d2 / (d2 - d6)
        m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        q = np.where(m[:, None], a + ac * w[:, None], q)                             # edge ac
        m = (d6 >= 0) & (d5 <= d6)
        q = np.where(m[:, None], c, q)                                               # vertex c
        w = d1 / (d1 - d3)
        m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        q = np.where(m[:, None], a + ab * w[:, None], q)                             # edge ab
        m = (d3 >= 0) & (d4 <= d3)
        q = np.where(m[:, None], b, q)                                               # vertex b
        m = (d1 <= 0) & (d2 <= 0)
        q = np.where(m[:, None], a, q)                                               # vertex a
    return np.linalg.norm(p - q, axis=1)


def surface_distance(X, T, reach=1.0):
    """distance from every point of X to the triangulated surface T; distances beyond `reach` mm (already far more
    than ACCEPT_GAP) are reported as `reach`. X is processed in its own order in chunks: _samples emits the points of
    one triangle together, so a chunk is small in space and meets few triangles of T"""
    out = np.full(len(X), float(reach))
    if not len(T) or not len(X):
        return out
    lo, hi = T.min(1) - reach, T.max(1) + reach
    for s in range(0, len(X), 64):
        P = X[s:s + 64]
        sel = np.where(np.all((hi >= P.min(0)) & (lo <= P.max(0)), axis=1))[0]
        if not len(sel):
            continue
        for t0 in range(0, len(sel), 256):
            tt = T[sel[t0:t0 + 256]]
            nP, nT = len(P), len(tt)
            pp = np.repeat(P, nT, axis=0)
            dd = _point_triangle(pp, np.tile(tt[:, 0], (nP, 1)), np.tile(tt[:, 1], (nP, 1)), np.tile(tt[:, 2], (nP, 1)))
            out[s:s + 64] = np.minimum(out[s:s + 64], dd.reshape(nP, nT).min(1))
    return out


def surface_deviation(B, P, n=4000, tri=None):
    """boolean-free two-sided surface deviation of solids B and P -> (largest sampled distance mm, symmetric
    difference volume mm3 = the distance integrated over each surface, the larger of the two); tri: a dict that
    receives the two triangulations (for vertex_gap_tri)"""
    TB, TP = _triangles(B), _triangles(P)
    if tri is not None:
        tri.update(B=TB, P=TP)
    hd, vol = 0.0, 0.0
    for S, T in ((TB, TP), (TP, TB)):
        X, Wt = _samples(S, n)
        d = surface_distance(X, T)
        hd = max(hd, float(d.max()) if len(d) else float('inf'))
        vol = max(vol, float((d * Wt).sum()))
    return hd, vol


def vertex_gap_fast(S, T):
    """vertex_gap(S, T) measured on T's exact triangulation (vertex_gap_tri; 174 of the 194 s the straight test took on
    a 942-face purlin went to BRepExtrema), BRepExtrema itself where T cannot be triangulated"""
    try:
        return vertex_gap_tri(S, _triangles(T))
    except Exception as e:
        if is_oom(e):
            raise
        return vertex_gap(S, T)


def vertex_gap_tri(S, T_tri, reach=1.0):
    """vertex_gap(S, T) from T's triangulation: the largest distance from a vertex of solid S to the surface of solid T
    (mm). T has planar faces, whose triangulation is exact (its nodes are the faces' own vertices), so this is the
    distance vertex_gap measures - one numpy pass instead of one BRepExtrema computation per vertex against every face
    (26 - 89 s on parts of 300 - 900 faces). Distances beyond `reach` (far more than ACCEPT_GAP) count as `reach`"""
    V = np.array([tuple(v) for v in S.vertices()], float) if S.vertices() else np.zeros((0, 3))
    if not len(V) or not len(T_tri):
        return float('inf')
    V = V[np.lexsort((V[:, 2], V[:, 1], V[:, 0]))]          # neighbours together: surface_distance works in chunks
    return float(surface_distance(V, T_tri, reach).max())


def _bop(kind, a, b, fuzzy):
    """boolean on independent copies (the operands are never modified)"""
    import steelbuild
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Common
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    op = {'cut': BRepAlgoAPI_Cut, 'common': BRepAlgoAPI_Common}[kind]()
    args, tools = steelbuild._shape_list(), steelbuild._shape_list()
    args.Append(BRepBuilderAPI_Copy(a, True, False).Shape())
    tools.Append(BRepBuilderAPI_Copy(b, True, False).Shape())
    op.SetArguments(args)
    op.SetTools(tools)
    op.SetFuzzyValue(fuzzy)
    op.SetNonDestructive(True)
    op.Build()
    return op.Shape() if op.IsDone() else None


def _placed(shape, c0, rot):
    from OCP.gp import gp_Trsf, gp_Vec, gp_Ax1, gp_Pnt, gp_Dir
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(*[float(x) for x in c0]))
    if rot:
        r = gp_Trsf()
        r.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(*rot[0])), rot[1])
        t = r.Multiplied(t)
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


def boolean_symdiff(B, P, tol):
    """symmetric difference volume of B and P from the first sound boolean measurement (see SOUND_FRAMES), or None"""
    import steelbuild
    vB, vP = B.volume, P.volume
    bb = B.bounding_box()
    c0 = [-round(bb.center().X), -round(bb.center().Y), -round(bb.center().Z)]
    for rot in SOUND_FRAMES:
        Bl, Pl = _placed(B.wrapped, c0, rot), _placed(P.wrapped, c0, rot)
        for fz in SOUND_FUZZY:
            # sound: d1, d2 >= -tol, c >= half the smaller volume, d1 + c = vB and d2 + c = vP within tol - tested
            # boolean by boolean (common, then each cut), the next only while the test holds (the booleans are
            # independent: the same test, fewer booleans when it fails)
            r3 = _bop('common', Bl, Pl, fz)
            if r3 is None:
                continue
            c = steelbuild._volume(r3)
            if c < 0.5 * min(vB, vP):
                continue
            r1 = _bop('cut', Bl, Pl, fz)
            if r1 is None:
                continue
            d1 = steelbuild._volume(r1)
            if d1 < -tol or abs(d1 + c - vB) > tol:
                continue
            r2 = _bop('cut', Pl, Bl, fz)
            if r2 is None:
                continue
            d2 = steelbuild._volume(r2)
            if d2 >= -tol and abs(d2 + c - vP) <= tol:
                return max(d1, 0.0) + max(d2, 0.0)
    return None


def coincide(B, P):
    """does the rebuilt solid P (built by steelbuild from the candidate schedule rows) coincide with the source solid B?
    -> (ok, check). try_part's criteria and limits; see the comment above for how the symmetric difference is measured"""
    from build123d import CenterOf
    if not P.is_valid:
        return False, dict(reason='rebuilt solid not valid')
    if len(P.solids()) != 1:
        return False, dict(reason='rebuilt solid in %d pieces' % len(P.solids()))
    vB, vP = B.volume, P.volume
    bb1, bb2 = B.bounding_box(), P.bounding_box()
    dbb = max(abs(bb1.min.X - bb2.min.X), abs(bb1.min.Y - bb2.min.Y), abs(bb1.min.Z - bb2.min.Z),
              abs(bb1.max.X - bb2.max.X), abs(bb1.max.Y - bb2.max.Y), abs(bb1.max.Z - bb2.max.Z))
    aB = B.area
    dcen = (B.center(CenterOf.MASS) - P.center(CenterOf.MASS)).length
    cen_lim = ACCEPT_SYMDIFF_MM * aB * (bb1.diagonal / 2) / vB
    chk = dict(bbox_mm=dbb, centroid_mm=dcen, centroid_limit_mm=cen_lim, vol_rel=abs(vP - vB) / vB)
    if dbb > ACCEPT_BBOX:
        return False, dict(chk, reason='bbox differs %.3f mm' % dbb)
    if dcen > cen_lim:
        return False, dict(chk, reason='centroid differs %.3f of %.3f mm' % (dcen, cen_lim))
    if abs(vP - vB) > ACCEPT_SYMDIFF_MM * aB:          # |vB - vP| <= symmetric difference: a cheap necessary test
        return False, dict(chk, reason='volume differs %.2e' % chk['vol_rel'])
    tri = {}
    hd, sdv = surface_deviation(B, P, tri=tri)
    chk.update(surface_mm=hd, symdiff_surface_mm=sdv / aB)
    if hd > ACCEPT_GAP:
        return False, dict(chk, reason='surfaces differ %.3f mm' % hd)
    if sdv / aB > ACCEPT_SYMDIFF_MM:
        return False, dict(chk, reason='symdiff %.2e mm' % (sdv / aB))
    gap = max(vertex_gap_tri(B, tri['P']), vertex_gap_tri(P, tri['B']))
    chk['gap_mm'] = gap
    if gap > ACCEPT_GAP:
        return False, dict(chk, reason='vertex gap %.3f mm' % gap)
    sb = boolean_symdiff(B, P, 0.1 * ACCEPT_SYMDIFF_MM * aB)
    chk['symdiff_boolean_mm'] = None if sb is None else sb / aB
    if sb is not None and sb / aB > ACCEPT_SYMDIFF_MM:
        return False, dict(chk, reason='symdiff %.2e mm (boolean)' % (sb / aB))
    chk['symdiff_mm'] = max(sdv, sb or 0.0) / aB
    chk['symdiff_rel'] = max(sdv, sb or 0.0) / vB
    chk['symdiff_method'] = 'surface+boolean' if sb is not None else 'surface'
    return True, chk


FALLBACKS = ('sweep', 'cut tools')       # tried in this order when the straight-extrusion test fails


# ======================================================================================== acceptance: verify.py's rule
# A candidate is accepted only if the part rebuilt from its schedule rows (build_candidates: exactly what build_model.py
# builds) passes the checks verify.py will apply to it: verify.check - the same function, tolerances and allowance - on
# verify.py's references, every limit times VERIFY_MARGIN (stricter, never looser). The IFC is the authoritative
# reference: the source check holds the part to it; the delivered check allows the delivered file's own deviation from a
# closed source. The references (see references()):
#   source     verify.source_props (--ifc): the kernel's solids, or a faceted source's loose faces sewn into solids; an
#              open surface gives none (source_open); without --ifc: the record's faces when they were taken from the IFC
#              at full precision (exact_sources.csv faces_source 'ifc'; they are the source's own faces);
#   delivered  verify.delivered_props (--step): the delivered STEP's faceted part; without --step: the record's faces when
#              they were taken from the delivered STEP. (Faces from the IFC and no --step: the delivered check is implied
#              by the source check: |part - delivered| <= |part - source| + the allowance |source - delivered|.)
VERIFY_MARGIN = 0.9
VCHECK_KEYS = ('source_check', 'delivered_check', 'src_vol_rel_diff', 'src_centroid_diff_mm', 'src_bbox_diff_mm',
               'vol_rel_diff', 'centroid_diff_mm', 'bbox_diff_mm', 'delivered_facet_dev_vol_rel',
               'delivered_facet_dev_centroid_mm', 'delivered_facet_dev_bbox_mm', 'delivered_within_allowance_only', 'size_mm')
_FACES = {}                 # part id -> faces_source of exact_sources.csv ('ifc' | 'delivered_step' | 'none')
_SRC_REF = None             # part id -> verify.source_props entry (with --ifc); None: not computed
_DEL_REF = None             # part id -> verify.delivered_props entry (with --step); None: not computed


def faces_from_ifc(rec):
    """the record's faces were taken from the IFC at full precision (exact_sources.csv, else the record's 'source')"""
    fs = _FACES.get(rec['part_id'])
    return fs == 'ifc' if fs else rec.get('source') == SRC_IFC


def acceptance_limits(rec):
    """(ACCEPT_BBOX, ACCEPT_GAP) of a record: faces taken from the IFC at full precision carry no grid noise to absorb -
    a genuine extrusion recovers from them to < 1e-6 mm - so the bounding box and the vertex gap must stay within the
    faceted source tolerance verify.py applies (TOL_GRID_BBOX, 0.02 mm); faces from the delivered STEP keep the limits
    of its 0.01 mm grid"""
    if faces_from_ifc(rec):
        import verify
        return min(ACCEPT_BBOX_GRID, verify.TOL_GRID_BBOX), min(ACCEPT_GAP_GRID, verify.TOL_GRID_BBOX)
    return ACCEPT_BBOX_GRID, ACCEPT_GAP_GRID


def _own_props(rec):
    """the record's faces as a reference: volume, centre and bounding box of the polyhedron they state"""
    import stepfacets
    v, c, lo, hi = stepfacets.mass([{'outer': s['faces'], 'voids': s.get('voids', [])} for s in rec['solids']])
    return {'v': float(v), 'c': [float(x) for x in c], 'lo': [float(x) for x in lo], 'hi': [float(x) for x in hi]}


def references(rec):
    """-> (delivered reference, source reference, description) of a record for verify.check: verify.py's own when
    recover.py has them (--step, --ifc), else the record's faces by where they came from"""
    import verify
    pid, ifc = rec['part_id'], faces_from_ifc(rec)
    if _DEL_REF is not None:
        ref = _DEL_REF.get(pid)
        d = 'delivered STEP' if ref is not None else 'none (the delivered STEP lacks the part)'
    elif not ifc:
        ref, d = _own_props(rec), "the record's faces (from the delivered STEP)"
    else:
        ref, d = None, 'not given (no --step: implied by the source check)'
    if _SRC_REF is not None:
        e = _SRC_REF.get(pid)
        src = verify.source_reference(e)
        s_ = ('none (the kernel gives no geometry)' if src is None else 'open surface (source_open)' if src.get('open')
              else 'IFC, ' + verify.SOURCE_REFERENCE.get(e.get('kind'), e.get('kind') or ''))
    elif ifc:
        src, s_ = _own_props(rec), "the record's faces (the IFC's own faceted geometry, full precision)"
    else:
        src, s_ = None, 'not given (no --ifc)'
    return ref, src, f'source: {s_}; delivered: {d}'


def _devs(row):
    out = []
    if row.get('src_centroid_diff_mm') not in (None, ''):
        out.append('source: volume %s, centroid %s mm, bbox %s mm' % (row['src_vol_rel_diff'], row['src_centroid_diff_mm'],
                                                                      row['src_bbox_diff_mm']))
    if row.get('centroid_diff_mm') not in (None, ''):
        out.append('delivered: volume %s, centroid %s mm, bbox %s mm (allowance %s, %s mm, %s mm)' % (
            row['vol_rel_diff'], row['centroid_diff_mm'], row['bbox_diff_mm'], row.get('delivered_facet_dev_vol_rel'),
            row.get('delivered_facet_dev_centroid_mm'), row.get('delivered_facet_dev_bbox_mm')))
    return '; '.join(out)


def verification_check(rec, cands=None, solids=None):
    """-> (ok, values): the part rebuilt from the candidate descriptions (or the given solids), measured as verify.py
    measures it, through verify.check on the record's references (references()) with every limit times VERIFY_MARGIN.
    ok: it would be a match - the delivered check passes where a delivered reference exists, the source check where a
    closed source exists - and at least one of the two references exists"""
    import verify
    built = build_candidates(rec['part_id'], cands) if solids is None else solids
    if not built or not all(s.is_valid for s in built):
        return False, dict(reason='rebuilt part not valid')
    v, c, lo, hi = verify._props(built)
    ref, src, how = references(rec)
    row = verify.check(rec.get('geometry') or 'recovered', v, c, lo, hi, ref, src, scale=VERIFY_MARGIN)
    out = {k: row[k] for k in VCHECK_KEYS if row.get(k) not in (None, '')}
    out.update(margin=VERIFY_MARGIN, references=how)
    closed = src is not None and not src.get('open')
    if ref is None and not closed:
        out['reason'] = 'no reference to verify the rebuilt part against (%s)' % how
        return False, out
    fail = [n for n, bad in (('the source', closed and row.get('source_check') != 'exact'),
                             ('the delivered model', ref is not None and row.get('delivered_check') != 'match')) if bad]
    if fail:
        out['reason'] = 'would fail verification against %s (%s; limits x %g)' % (' and '.join(fail), _devs(row), VERIFY_MARGIN)
        return False, out
    return True, out


# a fallback result written to STEP (steelbuild.write_step, as build_model.py writes it) and read back must reproduce
# the part in memory, within e2e.py's reproduction limits
RT_VOL_REL, RT_CEN = 1e-5, 0.005


def roundtrip_check(rec, cands):
    """-> (ok, values): the STEP file steelbuild.write_step writes of the part rebuilt from the candidate, read back
    (e2e.read_step), against the part in memory: the same bodies, every solid valid and closed, nothing outside a solid,
    volume within RT_VOL_REL and centre within RT_CEN mm"""
    import shutil, tempfile
    import steelbuild, verify, e2e
    pid = rec['part_id']
    built = build_candidates(pid, cands)
    v, c, lo, hi = verify._props(built)
    d = tempfile.mkdtemp(prefix='recover_rt_')
    try:
        fn = os.path.join(d, 'part.step')
        bad = steelbuild.write_step([({'part_id': pid, 'name': ''}, built)], fn) or 0
        got = e2e.read_step(fn).get(pid)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if got is None:
        return False, dict(reason='STEP read-back lacks the part')
    dv = abs(got['v'] - v) / max(abs(v), 1e-9)
    dc = float(np.linalg.norm(np.asarray(got['c']) - np.asarray(c)))
    out = dict(rt_vol_rel=dv, rt_centroid_mm=dc, rt_bodies=[verify.n_shells(built), got['n_shells']])
    why = [w for w, b in (('a solid written is not valid or not closed', bad), ('bodies lost or added', got['n_shells'] != verify.n_shells(built)),
                          ('a solid read back is not valid', got['invalid']), ('a solid read back is open', got['open']),
                          ('a surface read back lies outside any solid', got['stray']),
                          ('volume %.2e off' % dv, dv > RT_VOL_REL), ('centre %.4f mm off' % dc, dc > RT_CEN)) if b]
    if why:
        out['reason'] = 'STEP read-back does not reproduce the part (%s)' % ', '.join(why)
        return False, out
    return True, out


def is_oom(e):
    """an allocation that failed under the worker's memory limit (Python MemoryError or OpenCASCADE's
    Standard_OutOfMemory / std::bad_alloc as the bindings raise them)"""
    if isinstance(e, MemoryError):
        return True
    t = type(e).__name__ + ' ' + str(e)
    return 'OutOfMemory' in t or 'bad_alloc' in t


def _work(rec, note=None):
    """straight extrusion first, then the fallbacks -> (part id, (candidates | None, reason, method, fallback log,
    extra)); note(stage, straight reason, fallbacks tried) is called before every stage (the parent's record of where a
    part was when its worker had to be stopped). The record's acceptance limits (acceptance_limits) hold while it is
    processed. An allocation failure is not a result: it propagates"""
    global ACCEPT_BBOX, ACCEPT_GAP
    keep = (ACCEPT_BBOX, ACCEPT_GAP)
    ACCEPT_BBOX, ACCEPT_GAP = acceptance_limits(rec)
    try:
        return _work_limits(rec, note)
    finally:
        ACCEPT_BBOX, ACCEPT_GAP = keep


def _work_limits(rec, note):
    note = note or (lambda *a: None)
    note('straight test', None, [])
    try:
        got, why = try_part(rec)
    except Exception as e:
        if is_oom(e):
            raise
        got, why = None, f'error {type(e).__name__}'
    extra = {}
    if got:
        # the straight test as in v7, with one exception: a straight extrusion that would fail verification while the
        # part rebuilt from its exact faces passes is not taken (in the 33 models with v7's references: 4 purlins of
        # 35 - 40 m in each of two giorgi models). Where both would fail, the recovery is kept as in v7
        note('straight test (verification check)', None, [])
        ok, vc = verification_check(rec, got)
        extra = {'verify_check': vc}
        if ok:
            return rec['part_id'], (got, why, 'straight', [], extra)
        import steelbuild
        ok_exact, ec = verification_check(rec, solids=steelbuild.exact_part(rec))
        extra['exact_check'] = ec
        if not ok_exact:
            return rec['part_id'], (got, why, 'straight', [], extra)
        got, why = None, vc['reason'] + '; the exact rebuild passes'
    tried = []
    if why != 'source solid not valid':
        for fb in FALLBACKS:
            note(fb, why, tried)
            extra = {}
            try:
                if fb == 'sweep':
                    import recover_sweep
                    g2, w2 = recover_sweep.try_sweep(rec)
                else:
                    import recover_cuts
                    g2, w2 = recover_cuts.try_cut_tools(rec)
                if g2:
                    note(fb + ' (verification check)', why, tried)
                    ok, vc = verification_check(rec, g2)
                    extra = {'verify_check': vc}
                    if not ok:
                        g2, w2 = None, vc['reason']
                if g2:
                    note(fb + ' (STEP round trip)', why, tried)
                    ok, rc = roundtrip_check(rec, g2)
                    extra['roundtrip_check'] = rc
                    if not ok:
                        g2, w2 = None, rc['reason']
            except Exception as e:
                if is_oom(e):
                    raise
                g2, w2 = None, f'error {type(e).__name__}: {e}'
            if g2:
                return rec['part_id'], (g2, 'ok', fb, tried, extra)
            tried.append((fb, w2))
    return rec['part_id'], (None, why, None, tried, {})


# ======================================================================================== budgeted worker processes
TIME_BUDGET_S = 1800.0      # per part (the slowest part of the 33 models takes a small fraction: recover_timing.json)
MEM_BUDGET_GB = 6.0         # per worker; at most 80 % of the machine's memory / jobs
RECYCLE_MB = 2048           # a worker whose resident size stays above this after a part is replaced by a fresh one
WATCH_S = 0.5               # watchdog period
STALL_S = 300.0             # a worker that used less than 1 s of CPU in this long is stuck (a native fault): stopped
PROGRESS_S = 10.0           # recover_progress.json (the parts in flight) is rewritten this often while recovery runs
try:
    import resource as _resource
    RLIMIT = _resource.RLIMIT_DATA  # heap and private mappings: the memory a part's computation allocates
except (ImportError, AttributeError):
    RLIMIT = None

_RECS = None                # the faceted parts (set before the workers are forked: they inherit it)


def _proc_mb(pid, key='VmRSS'):
    try:
        with open(f'/proc/{pid}/status') as fh:
            for line in fh:
                if line.startswith(key + ':'):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return None


def _cpu_s(pid):
    """CPU seconds (user + system) a process has used, or None"""
    try:
        with open(f'/proc/{pid}/stat') as fh:
            f = fh.read().rsplit(')', 1)[1].split()
        return (int(f[11]) + int(f[12])) / float(os.sysconf('SC_CLK_TCK'))
    except (OSError, ValueError, IndexError):
        return None


def _mem_total_mb():
    try:
        with open('/proc/meminfo') as fh:
            for line in fh:
                if line.startswith('MemTotal:'):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return None


def _worker(conn, limit_bytes):
    """child process: parts by index from the parent, one at a time, until told to stop (None). Messages to the
    parent: ('stage', i, stage, straight reason, fallbacks tried) before every stage of part i, then (kind, i, result,
    seconds, peak MB, retire) with kind 'done' or 'oom'; retire: the worker exits after this part"""
    import resource
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))    # a native fault ends the worker at once (no core dump of
    except (ValueError, OSError):                            # its ~9 GB address space while it holds the part)
        pass
    try:
        # the toolkit loaded and one boolean run before the limit is set: OpenCASCADE starts ~150 threads on the first
        # boolean and the worker's data mappings grow to ~6 GB at 0.4 GB resident (measured) - none of it a part's
        # memory
        import steelbuild  # noqa: F401
        import recover_sweep, recover_cuts, stepfacets  # noqa: F401
        from build123d import Box, Cylinder
        _ = (Box(10, 10, 10) - Cylinder(2, 20)).volume
    except Exception:
        pass
    if limit_bytes and RLIMIT is not None:
        try:
            soft, hard = resource.getrlimit(RLIMIT)
            lim = int((_proc_mb(os.getpid(), 'VmData' if RLIMIT == resource.RLIMIT_DATA else 'VmSize') or 0) * 2 ** 20) + int(limit_bytes)
            if hard != resource.RLIM_INFINITY:
                lim = min(lim, hard)
            resource.setrlimit(RLIMIT, (lim, hard))
        except (ValueError, OSError):
            pass
    while True:
        try:
            i = conn.recv()
        except (EOFError, OSError):
            return
        if i is None:
            return
        try:
            with open('/proc/self/clear_refs', 'w') as fh:     # peak resident size counted from here (Linux)
                fh.write('5')
        except OSError:
            pass
        t0 = time.time()

        def note(stage, why, tried):
            conn.send(('stage', i, stage, why, list(tried)))
        kind = 'done'
        try:
            res = _work(_RECS[i], note)[1]
        except Exception as e:
            if is_oom(e):
                kind, res = 'oom', None
            else:                           # outside every stage's own error handling: the part stays exact
                res = (None, f'error {type(e).__name__}: {e}', None, [], {'isolated': 'worker error'})
        retire = kind == 'oom' or (_proc_mb(os.getpid()) or 0.0) > RECYCLE_MB
        try:
            conn.send((kind, i, res, time.time() - t0, _proc_mb(os.getpid(), 'VmHWM'), retire))
        except (BrokenPipeError, OSError):
            return
        if retire:
            return                          # a fresh worker takes over: memory not given back stays out of the budget


def _isolated(state, why):
    """the result of a part whose worker had to be stopped: exact, with the stage it was in and the reason"""
    stage, straight_why, tried = state.get('stage') or 'straight test', state.get('why'), list(state.get('tried') or [])
    if stage == 'straight test' or straight_why is None:
        return (None, why, None, tried, {'isolated': why, 'stage': stage})
    fb = stage.replace(' (verification check)', '').replace(' (STEP round trip)', '')
    return (None, straight_why, None, tried + [(fb, why)], {'isolated': why, 'stage': stage})


def _cost(rec):
    """the order parts are handed out in: largest first, so a long part does not end the run alone (the results do not
    depend on the order)"""
    return sum(len(s['faces']) for s in rec['solids'])


def _run(recs, jobs, time_budget=TIME_BUDGET_S, mem_budget_mb=MEM_BUDGET_GB * 1024, timing=None, progress=None):
    """recovery of every part in budgeted worker processes -> [(part id, result)] in the order of recs. A part whose
    worker exceeds the time or the memory budget, or dies, is isolated: it stays exact with the stage and the reason
    recorded; no other part is affected and no finished part runs again (a part handed to a worker that died before
    starting it is handed out again, at most twice). progress: a file rewritten every PROGRESS_S seconds with the parts
    in flight (stage, seconds, resident MB) and the counts done / pending"""
    global _RECS
    import multiprocessing as mp
    from multiprocessing.connection import wait
    _RECS = recs
    ctx = mp.get_context('fork')
    n = len(recs)
    if not n:
        return []
    jobs = max(1, min(jobs, n))
    pending = collections.deque(sorted(range(n), key=lambda i: (-_cost(recs[i]), i)))
    results, stats, starts = {}, {}, collections.Counter()
    W = {}                                                          # conn -> worker state
    idle_deaths = [0]
    limit = int(mem_budget_mb * 2 * 2 ** 20) if mem_budget_mb else 0     # the backstop: twice the watchdog's budget

    def spawn():
        a, b = ctx.Pipe()
        p = ctx.Process(target=_worker, args=(b, limit), daemon=True)
        p.start()
        b.close()
        W[a] = dict(proc=p, idx=None)
        return a

    def give(c):
        w = W[c]
        if pending:
            i = pending.popleft()
            w.update(idx=i, t0=time.time(), stage='straight test', why=None, tried=[], peak=0.0, kill=None, started=False,
                     cpu=(time.time(), _cpu_s(w['proc'].pid)))
            msg = i
        else:
            w.update(idx=None, retiring=True)
            msg = None
        try:
            c.send(msg)
        except (BrokenPipeError, OSError):
            pass                                                    # its death is handled with the others

    def record(i, res, secs, peak, how):
        results[i] = res
        stats[i] = dict(seconds=round(secs, 2), peak_mb=round(peak or 0.0, 1), how=how)

    def bury(c):
        w = W.pop(c)
        try:
            c.close()
        except OSError:
            pass
        w['proc'].join(10)
        i = w.get('idx')
        if i is not None and i not in results:
            if w.get('started') or w.get('kill') or starts[i] >= 2:
                why = w.get('kill') or 'native crash (exit code %s)' % w['proc'].exitcode
                record(i, _isolated(w, why), time.time() - w['t0'], w.get('peak'), why)
            else:                                                   # it never started this part: hand it out again
                starts[i] += 1
                pending.appendleft(i)
        elif i is None and not w.get('retiring') and w['proc'].exitcode not in (0, None):
            idle_deaths[0] += 1
            if idle_deaths[0] > 3 * jobs:
                raise RuntimeError('recovery workers keep dying before taking a part')
        if pending and len(W) < jobs:
            give(spawn())

    for _ in range(jobs):
        give(spawn())
    oom_why = 'memory budget exceeded (%.1f GB)' % ((mem_budget_mb or 0) / 1024)
    t_prog = [0.0]

    def report(now):
        if not progress or now - t_prog[0] < PROGRESS_S:
            return
        t_prog[0] = now
        busy = sorted(([recs[w['idx']]['part_id'], w.get('stage'), round(now - w['t0'], 1), round(w.get('peak') or 0.0)]
                       for w in W.values() if w.get('idx') is not None), key=lambda r: -r[2])
        try:
            with open(progress + '.tmp', 'w') as fh:
                json.dump(dict(done=len(results), pending=len(pending), parts=n, busy=busy), fh, indent=0)
            os.replace(progress + '.tmp', progress)
        except OSError:
            pass
    while W:
        sentinels = [w['proc'].sentinel for w in W.values()]
        ready = set(wait(list(W) + sentinels, timeout=WATCH_S))
        for c in [c for c in list(W) if c in ready]:                # messages first, deaths after
            try:
                while c in W and c.poll():
                    msg = c.recv()
                    w = W[c]
                    if msg[1] != w.get('idx'):
                        continue
                    if msg[0] == 'stage':
                        w.update(stage=msg[2], why=msg[3], tried=msg[4], started=True)
                        continue
                    i = msg[1]
                    res = msg[2] if msg[0] == 'done' else _isolated(w, oom_why)
                    record(i, res, msg[3], msg[4], 'done' if msg[0] == 'done' else oom_why)
                    w['idx'] = None
                    if msg[5]:
                        w['retiring'] = True                        # it exits; its death brings a replacement
                    else:
                        give(c)
            except (EOFError, OSError):
                pass
        for c in [c for c in list(W) if not W[c]['proc'].is_alive()]:
            bury(c)
        now = time.time()
        for c, w in list(W.items()):                                # the watchdog
            if w.get('idx') is None:
                continue
            rss = _proc_mb(w['proc'].pid) or 0.0
            w['peak'] = max(w.get('peak') or 0.0, rss)
            cpu = _cpu_s(w['proc'].pid)
            t_cpu, c_cpu = w.get('cpu') or (now, cpu)
            if cpu is not None and c_cpu is not None and cpu - c_cpu >= 1.0:
                w['cpu'] = (now, cpu)                               # progress
            if time_budget and now - w['t0'] > time_budget:
                w['kill'] = 'time budget exceeded (%d s)' % time_budget
            elif mem_budget_mb and rss > mem_budget_mb:
                w['kill'] = oom_why
            elif cpu is not None and c_cpu is not None and now - t_cpu > STALL_S:
                w['kill'] = 'stalled (no CPU progress for %d s: native fault)' % STALL_S
            if w.get('kill'):
                w['proc'].kill()
                bury(c)
        report(now)
    if progress:
        try:
            os.remove(progress)
        except OSError:
            pass
    if timing is not None:
        timing['stats'] = stats
    return [(recs[i]['part_id'], results[i]) for i in range(n)]


def emit(pid, desc, new_id, designation=''):
    """schedule rows of one recovered solid description: the solid (role body) and, recursively, its cut tools (role
    cut_tool), each a profile row (+ outline) and a solids.csv row; per solid its plane cuts, then one cut of kind 'solid'
    per tool; a path (paths.json) where the description has one. new_id(kind) -> next id for 'P', 'S', 'C'.
    -> (profiles, outlines, solids, cuts, paths)"""
    nodes = []

    def walk(d, role):
        k = len(nodes)
        nodes.append([d, role, []])
        for t in d.get('tools') or []:
            nodes[k][2].append(walk(t, 'cut_tool'))
        return k
    walk(desc, 'body')
    profiles, outlines, solids, cuts, paths, sids = [], {}, [], [], {}, []
    for d, role, kids in nodes:
        prid = new_id('P')
        if d.get('profile'):
            profiles.append(dict(d['profile'], profile_id=prid, designation=designation))
        else:
            profiles.append({'profile_id': prid, 'kind': 'POLY', 'designation': designation, 'pos_x': 0.0, 'pos_y': 0.0, 'pos_angle': 0.0})
            outlines[prid] = d['outline']
        sid = new_id('S')
        sids.append(sid)
        o, x, z, v = d['o'], d['x'], d['z'], d['vec']
        solids.append({'solid_id': sid, 'part_id': pid, 'role': role, 'opening_id': '', 'profile_id': prid,
                       'ox': o[0], 'oy': o[1], 'oz': o[2], 'xx': x[0], 'xy': x[1], 'xz': x[2], 'zx': z[0], 'zy': z[1], 'zz': z[2],
                       'vx': v[0], 'vy': v[1], 'vz': v[2], 'scale': 1.0})
        if d.get('path'):
            paths[sid] = d['path']
    for k, (d, role, kids) in enumerate(nodes):
        for cu in d.get('cuts') or []:
            cuts.append({'cut_id': new_id('C'), 'solid_id': sids[k], 'kind': 'plane', 'px': cu['p'][0], 'py': cu['p'][1], 'pz': cu['p'][2],
                         'nx': cu['n'][0], 'ny': cu['n'][1], 'nz': cu['n'][2], 'tool_solid_id': ''})
        for j in kids:
            cuts.append({'cut_id': new_id('C'), 'solid_id': sids[k], 'kind': 'solid', 'px': '', 'py': '', 'pz': '',
                         'nx': '', 'ny': '', 'nz': '', 'tool_solid_id': sids[j]})
    return profiles, outlines, solids, cuts, paths



class MiniSchedules:
    """the schedule rows of one part's candidate solids held in memory exactly as steelbuild.Schedules holds them when
    read back from the files: every CSV value as the text csv writes for it, paths as JSON gives them back"""

    def __init__(self, profiles, outlines, solids, cuts, paths):
        txt = lambda r: {k: ('' if v is None else str(v)) for k, v in r.items()}
        self.parts = []
        self.profiles = {r['profile_id']: txt(r) for r in profiles}
        self.outlines = json.loads(json.dumps(outlines))
        self.solids = {r['solid_id']: txt(r) for r in solids}
        self.cuts = [txt(r) for r in cuts]
        self.paths = json.loads(json.dumps(paths))
        self.boundaries, self.openings, self.exact = {}, [], {}
        self.body_of, self.cuts_of, self.open_of = {}, {}, {}
        for r in self.solids.values():
            if r['role'] == 'body':
                self.body_of.setdefault(r['part_id'], []).append(r['solid_id'])
        for c in self.cuts:
            self.cuts_of.setdefault(c['solid_id'], []).append(c)


def build_candidates(pid, cands):
    """the solids of one part built from candidate descriptions exactly as build_model.py builds them from the
    schedules (emit -> rows -> steelbuild.build_part)"""
    import steelbuild
    cnt = {'P': 0, 'S': 0, 'C': 0}

    def new_id(k):
        cnt[k] += 1
        return f'{k}{cnt[k]}'
    P, O, S, C, PA = [], {}, [], [], {}
    for d in cands:
        p_, o_, s_, c_, pa_ = emit(pid, d, new_id)
        P += p_
        O.update(o_)
        S += s_
        C += c_
        PA.update(pa_)
    return steelbuild.build_part({'part_id': pid, 'geometry': 'recovered'}, MiniSchedules(P, O, S, C, PA))

def count_tools(d):
    return sum(1 + count_tools(t) for t in d.get('tools') or [])


def note_of(method, got):
    sd = max(c['check']['symdiff_rel'] for c in got)
    if method == 'straight':
        return 'parameters recovered from the faceted source: section x axis x length - end planes (symdiff %.1e)' % sd
    if method == 'sweep':
        how = []
        for c in got:
            pa = c.get('path')
            if not pa:
                how.append('section x axis x length - end planes')
            else:
                n = len(pa['points'])
                how.append('section swept along %s path of %d points (paths.json, section %s%s)' % (
                    'a closed' if pa.get('closed') else 'an open', n, pa.get('section', 'perpendicular'),
                    ', scaled at %d points' % sum(1 for f in pa['scales'] if f != 1.0) if pa.get('scales') else ''))
        return 'parameters recovered from the faceted source: %s (symdiff %.1e)' % ('; '.join(sorted(set(how))), sd)
    nt = sum(count_tools(c) for c in got)
    return ('parameters recovered from the faceted source: section x axis x length - end planes - %d cut tools '
            '(solids.csv role cut_tool, each a section x axis x length - end planes - its own tools) (symdiff %.1e)' % (nt, sd))


def load_references(folder, ifc='', step='', jobs=1):
    """the acceptance's references (module globals the worker processes inherit): exact_sources.csv's faces_source per
    part, and with --ifc / --step verify.py's own source and delivered references of the faceted parts -> description"""
    global _FACES, _SRC_REF, _DEL_REF
    fs = os.path.join(folder, 'exact_sources.csv')
    _FACES = {r['part_id']: r['faces_source'] for r in csv.DictReader(open(fs, newline='', encoding='utf-8'))} if os.path.exists(fs) else {}
    recs = [json.loads(l) for l in open(os.path.join(folder, 'exact_geometry.jsonl')) if l.strip()]
    want = {r['part_id'] for r in recs}
    import verify
    t0 = time.time()
    _DEL_REF = {k: v for k, v in verify.delivered_props(step).items() if k in want} if step else None
    t1 = time.time()
    _SRC_REF = verify.source_props(ifc, folder, jobs, keep_log=False, only=want) if ifc else None
    t2 = time.time()
    return dict(faces_source=dict(collections.Counter(_FACES.get(p, 'not listed') for p in want)),
                delivered='verify.delivered_props of %s (%d of %d parts, %.0f s)' % (os.path.basename(step), len(_DEL_REF), len(want), t1 - t0) if step else "the records' faces from the delivered STEP",
                source='verify.source_props of %s (%d of %d parts, %.0f s)' % (os.path.basename(ifc), len(_SRC_REF), len(want), t2 - t1) if ifc else "the records' faces from the IFC (faces_source ifc)")


def main():
    global FALLBACKS
    ap = argparse.ArgumentParser()
    ap.add_argument('folder')
    ap.add_argument('--jobs', type=int, default=os.cpu_count())
    ap.add_argument('--fallbacks', default=','.join(FALLBACKS),
                    help='fallbacks after the straight test, in order (comma separated: sweep, cut tools; empty: none)')
    ap.add_argument('--time-budget', type=float, default=TIME_BUDGET_S,
                    help='seconds one part may take before its worker is stopped and the part stays exact (0: none)')
    ap.add_argument('--mem-budget-gb', type=float, default=MEM_BUDGET_GB,
                    help='memory one worker may use (GB; at most 80%% of the machine memory / jobs; 0: none)')
    ap.add_argument('--ifc', default='', help='the source IFC: verify.py\'s source reference for the acceptance')
    ap.add_argument('--step', default='', help='the delivered STEP: verify.py\'s delivered reference for the acceptance')
    a = ap.parse_args()
    FALLBACKS = tuple(x.strip() for x in a.fallbacks.split(',') if x.strip())
    F = lambda n: os.path.join(a.folder, n)
    recs = [json.loads(l) for l in open(F('exact_geometry.jsonl')) if l.strip()]
    t_start = time.time()
    jobs = max(1, a.jobs or 1)
    refs = load_references(a.folder, a.ifc, a.step, jobs)
    print('recover: acceptance references:', json.dumps(refs))
    mem_mb = a.mem_budget_gb * 1024
    total = _mem_total_mb()
    if mem_mb and total:
        mem_mb = min(mem_mb, 0.8 * total / min(jobs, max(1, len(recs))))
    timing = {}
    res = dict(_run(recs, jobs, a.time_budget, mem_mb, timing, progress=F('recover_progress.json')))
    parts = list(csv.DictReader(open(F('parts.csv'))))
    pcols = list(csv.DictReader(open(F('profiles.csv'))).fieldnames)
    pcols += [c for c in ('sides', 'radius_inner', 'angle_inner') if c not in pcols]
    profiles = list(csv.DictReader(open(F('profiles.csv'))))
    scols = list(csv.DictReader(open(F('solids.csv'))).fieldnames)
    solids = list(csv.DictReader(open(F('solids.csv'))))
    ccols = list(csv.DictReader(open(F('cuts.csv'))).fieldnames)
    cuts = list(csv.DictReader(open(F('cuts.csv'))))
    outlines = json.load(open(F('profile_outlines.json')))
    paths = json.load(open(F('paths.json'))) if os.path.exists(F('paths.json')) else {}
    taken = {'P': {r['profile_id'] for r in profiles}, 'S': {r['solid_id'] for r in solids}, 'C': {r['cut_id'] for r in cuts}}
    cnt = {'P': len(profiles), 'S': len(solids), 'C': len(cuts)}

    def new_id(k):
        """next free id of a kind (P profile, S solid, C cut), counting on from the number of rows already there"""
        while True:
            cnt[k] += 1
            i = f'{k}{cnt[k]}'
            if i not in taken[k]:
                taken[k].add(i)
                return i
    reasons = collections.Counter()
    fb_reasons = collections.defaultdict(collections.Counter)
    keep_exact = []
    log = []
    byid = {p['part_id']: p for p in parts}
    # rows of the straight extrusions first (in part order, exactly as without fallbacks), then the fallbacks' rows
    order = [(0, rec) for rec in recs] + [(1, rec) for rec in recs]
    for rnd, rec in order:
        pid = rec['part_id']
        got, why, method, tried, extra = (tuple(res.get(pid, (None, 'missing', None, [], {}))) + (None, [], {}))[:5]
        extra = extra or {}
        if rnd == 0:
            for fb, w2 in tried:
                fb_reasons[fb][str(w2).split(' (')[0]] += 1
            if not got:
                reasons[why.split(' (')[0]] += 1
                keep_exact.append(rec)
                lg = {'part_id': pid, 'result': 'exact', 'method': '', 'reason': why, 'fallbacks': tried}
                if extra.get('isolated'):
                    lg.update(isolated=extra['isolated'], stage=extra.get('stage'))
                log.append(lg)
                continue
            if method != 'straight':
                continue
        elif not got or method == 'straight':
            continue
        label = method
        if method == 'sweep' and not any(c.get('path') for c in got):
            label = 'straight, tube test'          # a one-segment tube: a plain extrusion, found by the sweep test
        reasons['recovered' if method == 'straight' else f'recovered ({label})'] += 1
        for c in got:
            p_, o_, s_, c_, pa_ = emit(pid, c, new_id, byid[pid].get('designation', ''))
            profiles += p_
            outlines.update(o_)
            solids += s_
            cuts += c_
            paths.update(pa_)
        byid[pid]['geometry'] = 'recovered'
        byid[pid]['note'] = note_of(method, got)
        lg = {'part_id': pid, 'result': 'recovered', 'method': method, 'reason': '', 'fallbacks': tried,
              'n_tools': sum(count_tools(c) for c in got), 'paths': sum(1 for c in got if c.get('path')),
              'checks': [c['check'] for c in got]}
        for k in ('verify_check', 'exact_check', 'roundtrip_check'):
            if extra.get(k):
                lg[k] = extra[k]
        log.append(lg)

    def w(name, cols, rows):
        with open(F(name), 'w', newline='') as fh:
            wr = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
            wr.writeheader()
            for r in rows:
                wr.writerow(r)
    w('parts.csv', list(parts[0].keys()), parts)
    w('profiles.csv', pcols, profiles)
    w('solids.csv', scols, solids)
    w('cuts.csv', ccols, cuts)
    json.dump(outlines, open(F('profile_outlines.json'), 'w'), separators=(',', ':'))
    if paths:
        json.dump(paths, open(F('paths.json'), 'w'), separators=(',', ':'))
    with open(F('exact_geometry.jsonl'), 'w') as fh:
        for rec in keep_exact:
            fh.write(json.dumps(rec, separators=(',', ':')) + '\n')
    with open(F('recover_log.jsonl'), 'w') as fh:
        for r in log:
            fh.write(json.dumps(r, separators=(',', ':'), default=float) + '\n')
    json.dump(dict(reasons), open(F('recover_summary.json'), 'w'), indent=1)
    json.dump({fb: dict(c) for fb, c in fb_reasons.items()}, open(F('recover_fallbacks_summary.json'), 'w'), indent=1)
    # run time against the budgets (the one output that differs from run to run)
    st = timing.get('stats', {})
    rows = []
    for i, rec in enumerate(recs):
        x = st.get(i, {})
        got, why, method, tried, extra = (tuple(res.get(rec['part_id'])) + (None, [], {}))[:5]
        rows.append(dict(part_id=rec['part_id'], faces=_cost(rec), seconds=x.get('seconds'), peak_mb=x.get('peak_mb'),
                         result='recovered (%s)' % method if got else 'exact', isolated=(extra or {}).get('isolated')))
    secs = sorted((r['seconds'] or 0.0 for r in rows), reverse=True)
    tm = dict(seconds=round(time.time() - t_start, 1), parts=len(recs), jobs=jobs, references=refs,
              budgets=dict(time_s=a.time_budget, memory_mb=round(mem_mb, 1), rlimit='RLIMIT_DATA' if RLIMIT is not None else None),
              slowest_part_s=secs[0] if secs else 0.0, part_seconds_total=round(sum(secs), 1),
              part_seconds_p50=secs[len(secs) // 2] if secs else 0.0,
              largest_part_mb=max((r['peak_mb'] or 0.0 for r in rows), default=0.0),
              isolated=[r for r in rows if r['isolated']],
              slowest=sorted(rows, key=lambda r: -(r['seconds'] or 0.0))[:25],
              largest=sorted(rows, key=lambda r: -(r['peak_mb'] or 0.0))[:10])
    json.dump(tm, open(F('recover_timing.json'), 'w'), indent=1)
    print(json.dumps(dict(reasons)))
    print('recover: %d parts in %.0f s (%d jobs); slowest part %.1f s, largest %.0f MB; budgets %s s / %.0f MB; isolated %d'
          % (len(recs), tm['seconds'], jobs, tm['slowest_part_s'], tm['largest_part_mb'], a.time_budget, mem_mb,
             len(tm['isolated'])))

if __name__ == '__main__':
    # one module: recover_sweep / recover_cuts reach this one through `import recover`, so they see the limits a part is
    # processed with (acceptance_limits) and the references (load_references)
    sys.modules['recover'] = sys.modules[__name__]
    main()
