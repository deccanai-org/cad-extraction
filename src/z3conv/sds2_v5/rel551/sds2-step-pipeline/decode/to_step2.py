"""Stage 2: SDS2 job -> STEP with fabricated pieces (main material + connection plates/angles), 7.243 and 7.425 layouts.

Each placed piece (mem material block: rotation M, global origin o, piece id) becomes a solid:
  plate  : 2D convex hull of its vertices in the plate plane (thinnest bbox axis), extruded over the thickness
  bent   : bent plates (thinnest extent >> thickness): end-face section polygon extruded along the bend line
  rolled : AISC profile from job_mtrl (hollow sections keep their inner loop), extruded along local x over the vertex
           x-range; profile orientation (4 sign flips) chosen so the most vertices lie on the profile boundary;
           fitted to the vertex y/z bbox (round HSS: centred on the axis)
Members with no fabricated pieces (joists) fall back to the stage-1 member solid.
World point = o + M.T @ local  (validated on 50_Binney: plates 78% within 1in of the IFC part; on TRI NORTH 7.425,
solid volume vs the piece weight in subm_idx: W 99%, HSS 95%, L 93%, plates 83-100% within 10%).
By default every piece is first built from its own B-rep (brep.py: exact faces, copes and cuts, bolt holes and slots
cut in); the builders above are the fallback when a piece has no usable topology.
usage: python to_step2.py <job_dir> <out.step>
"""
import os, sys, csv, math, re, struct, collections
import numpy as np
from scipy.spatial import ConvexHull
from instances import material_instances, subm_vertices, piece_vertices
from piece_table import read_pieces, kind
from sds2job import read_shapes, read_version, read_members
import to_step as T
import brep

from OCP.gp import gp_Pnt, gp_Vec
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.ShapeFix import ShapeFix_Face
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDataStd import TDataStd_Name
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.Interface import Interface_Static
from OCP.IFSelect import IFSelect_RetDone

MM = 25.4


def _revisits(pts, tol=5e-3):
    """True if two non-adjacent ring points coincide (within tol): such rings pass shapely but not OCC / STEP."""
    P = np.asarray([np.asarray(q, float)[:2] if len(q) == 2 else np.asarray(q, float) for q in pts])
    n = len(P)
    if n < 4: return False
    D = np.linalg.norm(P[:, None, :] - P[None, :, :], axis=2)
    iu = np.triu_indices(n, 2)
    close = D[iu] < tol
    adj_wrap = (iu[0] == 0) & (iu[1] == n - 1)
    return bool(np.any(close & ~adj_wrap))


def _clean_loop(loop, tol=5e-3):
    """Drop near-duplicate and collinear points: tiny edges survive OCC's check but not the STEP round trip
    (7.516 HENRY FORD piece 8861 read back invalid)."""
    pts = [np.asarray(q, float) for q in loop]
    changed = True
    while changed and len(pts) > 3:
        changed = False
        for k in range(len(pts)):
            a, b, c = pts[k - 1], pts[k], pts[(k + 1) % len(pts)]
            ab, bc = b - a, c - b
            la, lb = np.linalg.norm(ab), np.linalg.norm(bc)
            if la < tol or (lb > 0 and np.linalg.norm(np.cross(ab, bc)) < 1e-4 * la * lb):   # duplicate / collinear
                del pts[k]; changed = True; break
    return pts


def _wire(loop):
    poly = BRepBuilderAPI_MakePolygon()
    for q in _clean_loop(loop):
        poly.Add(gp_Pnt(*(q * MM)))
    poly.Close()
    return poly.Wire()


def prism(loop_world, extrude_world, holes_world=()):
    """Planar face from an outer loop (+ inner loops for hollow sections), extruded along extrude_world.
    Returns None for degenerate input (zero-length extrusion, collinear loop) instead of raising."""
    if np.linalg.norm(extrude_world) < 1e-6:
        return None
    try:
        f = BRepBuilderAPI_MakeFace(_wire(loop_world), True)
        if not f.IsDone():
            return None
        for h in holes_world:
            f.Add(_wire(h))
        face = f.Face()
        if holes_world:                            # let OCC orient the inner wires opposite to the outer one
            fix = ShapeFix_Face(face); fix.FixOrientation(); face = fix.Face()
        sh = BRepPrimAPI_MakePrism(face, gp_Vec(*(extrude_world * MM))).Shape()
        if BRepCheck_Analyzer(sh).IsValid():
            return sh
        from OCP.ShapeFix import ShapeFix_Shape    # e.g. a self-touching section: repair, else reject
        fx = ShapeFix_Shape(sh); fx.Perform()
        return fx.Shape() if BRepCheck_Analyzer(fx.Shape()).IsValid() else None
    except Exception:
        return None


def trim_to_length(V, axis, L, tol=0.25):
    """Drop stray vertices along `axis` (e.g. a lone (-2,0,0) record) when the vertex span exceeds the piece length
    from subm_idx: keep the window of length L that holds the most vertices."""
    x = V[:, axis]
    if not L or L <= 0 or np.ptp(x) <= L + tol:
        return V
    xs = np.sort(np.unique(np.round(x, 4)))
    s = max(xs, key=lambda s0: np.sum((x >= s0 - 1e-4) & (x <= s0 + L + tol)))
    keep = (x >= s - 1e-4) & (x <= s + L + tol)
    kx = x[keep]
    faces_ok = kx.size and np.sum(np.abs(kx - kx.min()) < 1e-3) >= 3 and np.sum(np.abs(kx - kx.max()) < 1e-3) >= 3 \
        and kx.max() - kx.min() > 0.9 * L
    if (~keep).sum() > max(2, 0.1 * len(x)) and not faces_ok:
        return V                                   # length field and geometry disagree: keep all
    return V[keep]                                 # a few strays, or a full end face at both ends of the window
                                                   # (7.516 HENRY FORD angles: 5 marker points 600 in away)


def _end_face_share(x):
    """Share of vertices on the two most populated coordinate values (the two end faces of an extrusion)."""
    _, c = np.unique(np.round(x, 3), return_counts=True)
    return np.sort(c)[-2:].sum() / len(x)


def bent_plate_local(V, p):
    """Bent plate: extrusion of its end-face section. The section outline is the vertices lying on the min face of the
    extrusion axis, in file order; arc helper points (bend centres) can make that ring self-intersect, so the fewest
    points are dropped to get a simple polygon whose area matches the flat width x thickness (within 25%)."""
    from itertools import combinations
    from shapely.geometry import Polygon
    ext0 = V.max(0) - V.min(0)
    a = max((k for k in range(3) if ext0[k] > 0), key=lambda k: (round(_end_face_share(V[:, k]), 2), ext0[k]))
    V = trim_to_length(V, a, p["L"])
    lo, hi = V.min(0), V.max(0); ext = hi - lo
    i, j = [k for k in range(3) if k != a]
    ring = []
    for q in V[np.abs(V[:, a] - lo[a]) < 1e-3][:, [i, j]]:
        if not ring or np.abs(q - ring[-1]).max() > 1e-4:
            ring.append(q)
    if len(ring) > 1 and np.abs(ring[0] - ring[-1]).max() < 1e-4:
        ring.pop()
    target = p["W"] * p["T"]
    if len(ring) < 3 or target <= 0:
        return None
    best = None
    for drop in range(0, min(3, len(ring) - 3) + 1):
        for rm in combinations(range(len(ring)), drop):
            pts = [ring[k] for k in range(len(ring)) if k not in rm]
            if _revisits(pts):
                continue                           # revisits a vertex: valid for shapely, breaks after STEP export
            poly = Polygon(pts)
            if poly.is_valid and poly.area > 0:
                err = abs(poly.area - target) / target
                if best is None or err < best[0]:
                    best = (err, pts)
        if best and best[0] < 0.25:
            break
    if best is None or best[0] >= 0.25:
        # multi-bend sections whose ring can't be repaired: concave hull of the section points, tightest that fits
        import shapely
        from shapely.geometry import MultiPoint
        # section points from both end faces: some files list only part of the outline on the start face
        # (7.516 HENRY FORD bent plates: 8 of the L-section's points at x=min, the rest at x=max)
        allpts = [q for q in V[:, [i, j]]]
        for pts_set, ratio in [(ring, r) for r in (0.02, 0.05, 0.1, 0.2, 0.3, 0.5)] + [(allpts, r) for r in (0.02, 0.05, 0.1, 0.2)]:
            try:
                poly = shapely.concave_hull(MultiPoint(pts_set), ratio=ratio)
            except Exception:
                continue
            if poly.geom_type == "Polygon" and poly.is_valid and poly.area > 0:
                err = abs(poly.area - target) / target
                if best is None or err < best[0]:
                    cc = [np.array(c) for c in poly.exterior.coords[:-1]]
                    if not _revisits(cc):          # concave hulls can touch themselves at a point
                        best = (err, cc)
    if best is None or best[0] >= 0.35:
        return None
    loop = []
    for u, v in best[1]:
        q = np.zeros(3); q[i], q[j], q[a] = u, v, lo[a]; loop.append(q)
    e = np.zeros(3); e[a] = ext[a]
    return loop, e


def plate_local_area(poly_pts):
    from shapely.geometry import Polygon
    return Polygon(poly_pts).area


def plate_outline(V, t, a, b, target, hull_ring):
    """Notched / cut plates: the convex hull fills cut-outs (on Fan Pier a 1/8in sheet came out 2.3x its weight).
    Try the plate's own outline (vertices on one face, file order), then concave hulls; keep whichever polygon's
    area is closest to weight / (density x thickness), and only if it beats the convex hull and is within 15%."""
    import shapely
    from shapely.geometry import Polygon, MultiPoint
    # Some source piece records yield a zero or non-finite target area (data-3 7.425 / 7.433: ZeroDivisionError aborted
    # the whole job); with no usable weight-derived area keep the convex hull
    if not np.isfinite(target) or target <= 0:
        return None
    hull_err = abs(plate_local_area(hull_ring) - target) / target
    if hull_err < 0.05:
        return None
    face = V[np.abs(V[:, t] - V[:, t].min()) < 1e-3][:, [a, b]]
    ring = []
    for q in face:
        if not ring or np.abs(q - ring[-1]).max() > 1e-4:
            ring.append(q)
    cands = []
    if len(ring) >= 3:
        cands.append(ring)
    for ratio in (0.05, 0.1, 0.2, 0.3, 0.5):
        try:
            g = shapely.concave_hull(MultiPoint(V[:, [a, b]]), ratio=ratio)
        except Exception:                         # GEOS can fail on degenerate point sets; just skip this ratio
            continue
        if g.geom_type == "Polygon":
            cands.append([np.array(c) for c in g.exterior.coords[:-1]])
    best = None
    for c in cands:
        poly = Polygon(c)
        if not poly.is_valid or poly.area <= 0: continue
        if _revisits(c): continue                  # revisits a vertex
        err = abs(poly.area - target) / target
        if best is None or err < best[0]:
            best = (err, c)
    if best and best[0] < min(0.15, hull_err):
        return np.array(best[1])
    return None


def _flat_outline(V, p):
    """Plates stored as a 2D outline (8.007 350 Summer Street PL4x18: all vertices at z = -48, sometimes plus a stray
    point at z = 0): if >= 70% of the vertices share one coordinate and the extent along that axis is not the plate
    thickness, keep the points in that plane and extrude by T from the piece table."""
    if p is None or p["T"] <= 0:
        return None
    for a in range(3):
        vals, cnts = np.unique(np.round(V[:, a], 3), return_counts=True)
        z0 = vals[np.argmax(cnts)]
        on = np.abs(V[:, a] - z0) < 1e-3
        ext_a = np.ptp(V[:, a])
        if on.mean() >= 0.7 and on.sum() >= 3 and abs(ext_a - p["T"]) > 0.25 * p["T"]:
            i, j = [k for k in range(3) if k != a]
            pts = V[on][:, [i, j]]
            if np.ptp(pts[:, 0]) <= 0 or np.ptp(pts[:, 1]) <= 0:
                continue
            try:
                ring = pts[ConvexHull(pts).vertices]
            except Exception:
                continue
            outline = plate_outline(np.c_[pts, np.zeros(len(pts))], 2, 0, 1, p["wt"] / 0.2836 / p["T"], ring) if p["wt"] > 0 else None
            if outline is not None:
                ring = outline
            loop = []
            for u, v in ring:
                q = np.zeros(3); q[i], q[j], q[a] = u, v, z0; loop.append(q)
            e = np.zeros(3); e[a] = p["T"]
            return loop, e
    return None


def plate_local(V, p=None):
    """Returns (loop in local coords, extrusion vector local) for a plate from its vertices."""
    ext = V.max(0) - V.min(0)
    flat = _flat_outline(V, p)
    if flat is not None:
        return flat
    if p is not None and p["T"] > 0 and ext.min() > 1.5 * p["T"] + 0.05:   # thinnest extent >> thickness: bent
        bent = bent_plate_local(V, p)
        if bent is not None:
            return bent
    t = int(np.argmin(ext))
    a, b = [i for i in range(3) if i != t]
    pts2 = V[:, [a, b]]
    try:
        hull = ConvexHull(pts2)
        ring = pts2[hull.vertices]
    except Exception:
        lo, hi = pts2.min(0), pts2.max(0)
        ring = np.array([lo, [hi[0], lo[1]], hi, [lo[0], hi[1]]])
    if p is not None and p["T"] > 0 and p["wt"] > 0:
        outline = plate_outline(V, t, a, b, p["wt"] / 0.2836 / p["T"], ring)
        if outline is not None:
            ring = outline
    loop = []
    for p in ring:
        q = np.zeros(3); q[a], q[b], q[t] = p[0], p[1], V[:, t].min(); loop.append(q)
    e = np.zeros(3); e[t] = ext[t]
    return loop, e


def rolled_local(V, sh, L=None):
    """Profile loop in local (y,z) at x = xmin, extrusion along local x (L: piece length, used to drop stray points)."""
    loops = T.profile(sh)
    if not loops:
        return None
    V = trim_to_length(V, 0, L)
    outer = np.array(loops[0])                     # (u = depth dir, v = flange dir), centred
    # The tagged vertex scanner occasionally accepts an unrelated coordinate
    # hundreds of inches from an ordinary section. Use the section's own size
    # around the robust median to exclude those points from the profile fit.
    section_size = max(sh.d, sh.bf, 0.25)
    center = np.median(V[:, 1:], axis=0)
    fit = np.all(np.abs(V[:, 1:] - center) <= section_size + 0.1, axis=1)
    if fit.sum() >= 4 and fit.mean() >= 0.5:
        V = V[fit]
    lo, hi = V.min(0), V.max(0)
    cy, cz = (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2
    span = np.ptp(outer, axis=0)
    if (hi[1] - lo[1]) < 0.5 * span.min() and (hi[2] - lo[2]) < 0.5 * span.min():
        cy = cz = 0.0                              # round HSS/pipe: vertices only describe the seam; tube is on the axis
    best = None
    for swap in (False, True):
        uv = outer[:, ::-1] if swap else outer
        for su in (1, -1):
            for sv in (1, -1):
                P = np.c_[uv[:, 0] * su + cy, uv[:, 1] * sv + cz]
                # Score boundary agreement, then the section's y/z bbox. The
                # bbox distinguishes unequal angle legs that boundary hits
                # alone can exchange; all 8 flip/swap orientations are tried.
                seg_a, seg_b = P, np.roll(P, -1, axis=0)
                yz = V[:, 1:]
                dist = np.full(len(yz), 1e9)
                for A, Bp in zip(seg_a, seg_b):
                    AB = Bp - A; L2 = AB @ AB
                    if L2 == 0: continue
                    tt = np.clip(((yz - A) @ AB) / L2, 0, 1)
                    dist = np.minimum(dist, np.linalg.norm(yz - (A + np.outer(tt, AB)), axis=1))
                ext_err = np.abs(np.ptp(P, axis=0) - np.ptp(yz, axis=0))
                bbox_error = ext_err.sum()
                # FIX item 10: an orientation whose y/z extents match the vertex box within 0.05 in wins over
                # boundary hits alone (unequal angle legs exchanged: Binney G5 13,203 / 17,278 in the old builder)
                score = (bool(ext_err.max() <= 0.05), int(np.sum(dist < 0.02)), -round(float(bbox_error), 5))
                if best is None or score > best[0]:
                    best = (score, P, su, sv, swap)
    _, P, su, sv, swap = best
    loop = [np.array([lo[0], y, z]) for y, z in P]
    holes = [[np.array([lo[0], (v if swap else u) * su + cy, (u if swap else v) * sv + cz])
              for u, v in inner] for inner in loops[1:]]
    return loop, np.array([hi[0] - lo[0], 0, 0]), holes


TURNED = re.compile(r"(WS|TWS|HS|BLT|AB|RB|RD|NS|DBA|THD|STUD)\b|(WS|TWS|HS|RB|RD|AB|DBA)\d")   # studs, bolts, rods, anchors


def piece_instance_label(member_type, member_id, piece_name, piece_id, instance):
    """Unambiguous STEP component name, including repeated uses of one piece by a member."""
    return f"{member_type} #{member_id} / {piece_name} (piece {piece_id}, inst {instance})"


def mesh_vertices(job, sid):
    """Faceted pieces (weld studs, bolts, rods, concrete) store their mesh vertices as tag-0 records, count at +28."""
    from instances import _scan_vertices, _is_71
    if _is_71(job):                                # 7.1xx: every piece file is the same packed vertex list
        return subm_vertices(job, sid)
    fp = os.path.join(job, "subm", str(sid))
    if not os.path.exists(fp):
        return None                                  # piece file missing (partial extraction): no geometry
    b = open(fp, "rb").read()
    if len(b) < 40:
        return None
    nv = struct.unpack(">I", b[28:32])[0]
    V = [v for v in _scan_vertices(b, (0,), False) if any(v)]
    return np.array(V[:nv]) if nv >= 4 and len(V) >= 4 else None


def turned_local(V):
    """Studs/bolts/rods: rings of vertices at stations along one axis. Returns [(start, length, radius, axis)] local:
    each segment between consecutive stations takes a radius present at both ends (the larger one only when the
    segment is short, i.e. a head or nut; otherwise the shank)."""
    best = None
    for a in range(3):
        o = [k for k in range(3) if k != a]
        r = np.linalg.norm(V[:, o], axis=1)
        ok = r > 0.05
        if ok.sum() < 6: continue
        score = len(np.unique(np.round(r[ok], 3)))
        if best is None or score < best[0]:
            best = (score, a, r)
    if best is None:
        return None
    _, a, r = best
    x = np.round(V[:, a], 3)
    cnt = collections.Counter((xi, ri) for xi, ri in zip(x, np.round(r, 3)) if ri > 0.05)
    st = {}
    for (xi, ri), c in cnt.items():
        if c >= 3:                                 # a ring, not a stray point (e.g. the weld-fillet ring of a stud)
            st.setdefault(xi, set()).add(ri)
    xs = sorted(st)
    segs = []
    for x0, x1 in zip(xs, xs[1:]):
        common = sorted(st[x0] & st[x1])
        if not common: continue
        L = x1 - x0
        rr = next((c for c in reversed(common) if L <= 2.5 * c), common[0])
        segs.append((x0, L, rr, a))
    return segs or None


def concrete_local(V, p, M):
    """Concrete piece (footing / grade beam): a T-thick prism (volume = the cubic yards in its name). Its mesh also
    carries a reference level far above (world z 424 on TRI NORTH), so the solid is the bottom T band of the mesh
    along the local axis that points vertically, with the plan extent of the mesh points inside that band."""
    T = p["T"]
    if T <= 0:
        return None
    t = int(np.argmax(np.abs(M[:, 2])))            # local axis k maps to world M[k] -> vertical component M[k, 2]
    down = M[t, 2] > 0                              # local +t points up: the bottom is the local minimum
    lo_t = V[:, t].min() if down else V[:, t].max() - T
    lo, hi = V.min(0), V.max(0)
    plan = [k for k in range(3) if k != t]
    # plan size: L and W from the piece table, matched to the two plan axes by the full-mesh extents
    ext = hi - lo
    a, b = plan if abs(ext[plan[0]] - p["L"]) + abs(ext[plan[1]] - p["W"]) <= abs(ext[plan[0]] - p["W"]) + abs(ext[plan[1]] - p["L"]) \
        else plan[::-1]
    for k, d in ((a, p["L"]), (b, p["W"])):
        if d > 0 and abs(ext[k] - d) > 0.5:
            hi[k] = lo[k] + d
    lo[t], hi[t] = lo_t, lo_t + T
    return lo, hi


def _compound(shapes):
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRep import BRep_Builder
    c = TopoDS_Compound(); bb = BRep_Builder(); bb.MakeCompound(c)
    for s in shapes: bb.Add(c, s)
    return c


def special_solid(job, sid, p, M, o):
    """Solid for pieces without a vertex outline (weld studs, bolts, anchor rods, concrete), in world coords.
    Returns (shape, kind) or (None, reason)."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeBox
    from OCP.gp import gp_Ax2, gp_Dir
    global SPECIAL_NOTE
    SPECIAL_NOTE = ""
    V = mesh_vertices(job, sid)
    Rt = M.T
    if p["name"].startswith("Conc"):
        if V is None: return None, "concrete: no mesh"
        lo, hi = concrete_local(V, p, M) or (None, None)
        if lo is None: return None, "concrete: no dims"
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        base = [corners[0], corners[4], corners[6], corners[2]]           # z = lo face ring
        return prism([o + Rt @ q for q in base], Rt @ np.array([0, 0, hi[2] - lo[2]])), "concrete"
    if TURNED.match(p["name"]):
        Vt = subm_vertices(job, sid)                # rods keep a proper tagged outline; studs/bolts only the mesh
        segs = turned_local(Vt) if Vt is not None and len(Vt) >= 6 else None
        if not segs and V is not None:
            segs = turned_local(V)
        if not segs and p["W"] > 0 and p["L"] > 0:
            # rings not stacked on one axis (hooked / bent anchors, 7.605 NFCU DBA1/2): straight rod of the
            # piece's diameter and length along the mesh's longest direction
            Vx = V if V is not None else Vt
            if Vx is not None and len(Vx):
                a = int(np.argmax(np.ptp(Vx, 0)))
                segs = [(float(Vx[:, a].min()), p["L"], p["W"] / 2, a)]
                SPECIAL_NOTE = "straight rod of the piece diameter and length along the mesh's longest direction (hook / bend not modelled)"
        if not segs: return None, "fastener: no rings"
        parts = []
        for x0, L, r, a in segs:
            u = np.zeros(3); u[a] = 1.0
            q0 = np.zeros(3); q0[a] = x0
            P0 = (o + Rt @ q0) * MM; D = Rt @ u
            try:
                parts.append(BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*P0), gp_Dir(*D)), r * MM, L * MM).Shape())
            except Exception:
                pass
        if not parts: return None, "fastener: degenerate"
        return (parts[0] if len(parts) == 1 else _compound(parts)), "fastener"
    return None, "no geometry"


SPECIAL_NOTE = ""     # set by special_solid when it had to guess a shape (tagged by the caller)
USE_BREP = True       # exact faceted solids from the piece file's own topology (brep.py); False = approximate builders
USE_HOLES = True      # cut the piece's bolt holes / slots (brep.holes) into its exact solid
_BREP = {}
CONCRETE = set()      # (job, piece) whose exact volume matches SDS2's weight at concrete density
HOLES_CUT = collections.Counter()
BREP_WHY = {}         # (job, piece) -> why the exact B-rep was not used (stand-in reason)
HOLES_NOT_CUT = set() # (job, piece) whose decoded holes the boolean could not cut


def _extents_match(V, faces, p, tol=0.02):
    """B-rep extents equal the piece table's L x W x T (sorted, within 2%): the solid is the stock piece, cut."""
    dims = sorted(x for x in (p.get("L", 0), p.get("W", 0), p.get("T", 0)))
    if min(dims) <= 0:
        return False
    used = sorted({i for f in faces for i in f})
    ext = sorted(np.ptp(V[used], 0))
    return all(abs(e - d) <= tol * d + 1e-3 for e, d in zip(ext, dims))


def brep_placed(job, sid, p, M, o):
    """Piece's exact solid (built once per piece, cached) placed at o + M.T @ local, or None -> approximate builders.
    Accepted only when its volume is within 0.6-1.6x of SDS2's recorded weight (guards against misparsed layouts)."""
    from OCP.gp import gp_Trsf
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    if not USE_BREP:
        return None
    key = (job, sid)
    if key not in _BREP:
        sh = None
        try:
            with open(os.path.join(job, "subm", str(sid)), "rb") as f:
                data = f.read()
            r = brep.parse(data)
            BREP_WHY[key] = "piece file has no readable face topology"
            if r is not None:
                sh = brep.solid(*r)
                if sh is None:
                    BREP_WHY[key] = "piece faces do not sew into a closed solid"
            if sh is not None and not 0 < p["wt"] < 1e9:
                # no usable SDS2 weight (v4 refused the exact B-rep outright): accept it when its extents are the
                # piece table's L x W x T, or for a rolled piece when its longest extent is the table length
                used = sorted({i for f in r[1] for i in f}); ext = np.ptp(r[0][used], 0)
                okx = _extents_match(r[0], r[1], p) or (p.get("sec", 0) > 0 and p.get("L", 0) > 0
                                                        and abs(ext.max() - p["L"]) <= 0.02 * p["L"] + 0.05)
                if not okx:
                    sh = None; BREP_WHY[key] = "no SDS2 weight and B-rep extents differ from the piece table"
            elif sh is not None:
                g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g)
                r_ = abs(g.Mass()) / MM ** 3 * 0.2836 / p["wt"]
                if 3.1 < r_ < 3.45:
                    # weighed as concrete (150 pcf = steel / 3.267): slabs / walls not named "Conc" (8.007 350 Summer
                    # Street 5x494: 71,450 lb as steel, 21,868 lb as concrete vs SDS2 21,870)
                    CONCRETE.add(key)
                elif r_ <= 0.6 and _extents_match(r[0], r[1], p):
                    pass          # cut plate weighed as its rectangular stock (SUNY triangular stiffeners: 0.495)
                elif not 0.6 < r_ < 1.6:
                    sh = None
                    BREP_WHY[key] = f"piece B-rep volume {r_:.2f}x SDS2's weight (outside 0.6-1.6)"
            if sh is not None and USE_HOLES:
                H = brep.holes(data)
                HOLES[key] = H
                if H:
                    cut = brep.cut_holes(sh, H)
                    HOLES_CUT["pieces with holes"] += 1
                    HOLES_CUT["holes" if cut is not sh else "holes not cut"] += len(H)
                    if cut is sh:
                        HOLES_NOT_CUT.add(key)
                    sh = cut
        except FileNotFoundError:
            sh = None; BREP_WHY[key] = "no piece file (subm/<id> missing)"
        except Exception as e:
            sh = None; BREP_WHY[key] = f"piece B-rep error {type(e).__name__}"
        _BREP[key] = sh
    sh = _BREP[key]
    if sh is None:
        return None
    t = placement(M, o)
    if t is None:
        return None                                     # rotation not orthonormal: approximate builders apply M as-is
    if SHARED:
        return ("shared", sh, t)                        # convert() places the cached solid as an assembly component
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    return BRepBuilderAPI_Transform(sh, t, True).Shape()


_REF = {}
REF_OPEN = set()      # reference parts written as open shells (faces as stored, not a closed solid)
REF_BUDGET_S = float(os.environ.get("SDS2_REF_BUDGET_S", "5400"))   # time for building reference-model parts per job
REF_MAX_FACES = 20000                                               # larger imported meshes are left out (reported)


def brep_reference(job, sid, M, o):
    """Exact B-rep of a reference-model piece (no SDS2 weight exists to validate it): accepted when its faces sew into a
    closed, valid solid of sane size. Shared part + placement like brep_placed."""
    key = (job, sid)
    if key not in _REF:
        sh = None
        try:
            r = brep.parse(open(os.path.join(job, "subm", str(sid)), "rb").read())
            if r is not None and len(r[1]) <= REF_MAX_FACES:
                sh = brep.solid(*r)
                if sh is None:
                    # open imported mesh (data-3 n2: 99,656 of 101,751 parts): keep SDS2's stored faces as a sewn shell
                    sh = brep.shell(*r)
                    if sh is not None:
                        REF_OPEN.add(key)
            if sh is not None and (_absurd(sh, 1e5) or not BRepCheck_Analyzer(sh).IsValid()):
                sh = None
        except Exception:
            sh = None
        _REF[key] = sh
    sh = _REF[key]
    if sh is None:
        return None
    t = placement(M, o)
    if t is None:
        return None
    if SHARED:
        return ("shared", sh, t)
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    return BRepBuilderAPI_Transform(sh, t, True).Shape()


def placement(M, o):
    """gp_Trsf for world = o + M.T @ local (inches -> mm), or None if M isn't a rotation."""
    from OCP.gp import gp_Trsf
    from instances import _is_frame
    if not _is_frame(np.asarray(M, float)) or not np.isfinite(o).all():
        return None                                     # v4 wrote a NaN placement into Greenwood's STEP (#219849)
    R = M.T
    try:
        t = gp_Trsf()
        t.SetValues(*R[0], o[0] * MM, *R[1], o[1] * MM, *R[2], o[2] * MM)
        return t
    except Exception:
        return None


FORCE_FLAT = set()    # labels to write as placed copies (read-back repair pass, sds2_to_step)
DROP_LABELS = set()   # labels to leave out (still invalid after the repair pass); reported as skipped
# BRepCheck every placed exact part instance in memory (invalid placements become placed copies). Off by default: it
# found none of the read-back failures in regression (those are caught by the --verify repair pass) and costs ~verify
# time on the largest jobs. SDS2_CHECK_PLACED=1 enables it.
CHECK_PLACED = os.environ.get("SDS2_CHECK_PLACED", "0") == "1"
ASSEMBLY_CHECK_MAX = int(os.environ.get("SDS2_ASSEMBLY_CHECK_MAX", "5000"))
INVALID_DROPPED = []  # labels of instances with no valid form (reported as skipped in the manifest)
SHARED = False        # set by convert(): write each exact piece once, placed per instance as an assembly component
USE_BOLTS = True      # nominal heavy-hex bolts through coaxial hole stacks of >= 2 pieces
HOLES = {}            # (job, piece) -> decoded holes (piece-local), filled by brep_placed

# ASTM A325 / A490 heavy hex: head height, nut height by bolt diameter (in); across flats = 1.5 d + 1/8
HEX_H = {0.5: (5 / 16, 31 / 64), 0.625: (25 / 64, 39 / 64), 0.75: (15 / 32, 47 / 64), 0.875: (35 / 64, 55 / 64),
         1.0: (39 / 64, 63 / 64), 1.125: (11 / 16, 1 + 7 / 64), 1.25: (25 / 32, 1 + 7 / 32), 1.375: (27 / 32, 1 + 11 / 32),
         1.5: (15 / 16, 1 + 15 / 32)}


def assembly_check(first):
    """{part key: (local solid, first placement)} -> set of keys whose component reads back invalid from a STEP
    assembly. One temporary file holding every part once; results mapped by component order."""
    import tempfile
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS_Iterator
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.STEPControl import STEPControl_Reader
    keys = list(first)
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf")); st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    root = st.NewShape()
    for k in keys:
        local, trsf = first[k]
        st.AddComponent(root, st.AddShape(local, False), TopLoc_Location(trsf))
    st.UpdateAssemblies()
    fd, f = tempfile.mkstemp(suffix=".step"); os.close(fd)
    try:
        w = STEPCAFControl_Writer(); w.Transfer(doc, STEPControl_AsIs)
        if w.Write(f) != IFSelect_RetDone:
            return set()
        rd = STEPControl_Reader(); rd.ReadFile(f); rd.TransferRoots()
        top = rd.OneShape(); kids = []
        it = TopoDS_Iterator(top)
        while it.More(): kids.append(it.Value()); it.Next()
        if len(kids) == 1 and len(keys) > 1:                   # one extra compound level
            it = TopoDS_Iterator(kids[0]); kids = []
            while it.More(): kids.append(it.Value()); it.Next()
        if len(kids) != len(keys):
            print(f"  note: assembly check skipped ({len(kids)} components read for {len(keys)} parts)")
            return set()
        bad = set()
        for k, s in zip(keys, kids):
            ex = TopExp_Explorer(s, TopAbs_SOLID)
            while ex.More():
                if not BRepCheck_Analyzer(ex.Current()).IsValid():
                    bad.add(k); break
                ex.Next()
        return bad
    finally:
        try: os.remove(f)
        except OSError: pass


def bolt_local(d, grip, L=None):
    """Bolt along +z: head z in [-H, 0], shank z in [0, L] (nominal: grip + nut + 1/4 in stick-out), nut z in
    [grip, grip + N]."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism
    from OCP.gp import gp_Ax2, gp_Dir, gp_Vec
    H, N = HEX_H.get(round(d, 4), (0.625 * d, d))
    F = 1.5 * d + 0.125; R = F / np.sqrt(3)                     # hex circumradius from across-flats
    def hexp(z0, h):
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
        poly = BRepBuilderAPI_MakePolygon()
        for k in range(6):
            a = np.pi / 3 * k; poly.Add(gp_Pnt(R * np.cos(a) * MM, R * np.sin(a) * MM, z0 * MM))
        poly.Close()
        return BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(poly.Wire(), True).Face(), gp_Vec(0, 0, h * MM)).Shape()
    L = L if L and L > grip else grip + N + 0.25
    return _compound([hexp(-H, H), BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), d / 2 * MM, L * MM).Shape(),
                      hexp(grip, N)])


def bolt_stacks(C, A, D, T, I):
    """Group placed holes into coaxial stacks (same bolt diameter, parallel axes, lateral offset < 1/16 in, within
    6 in); keep stacks through >= 2 piece instances -> list of (entry point, unit axis, grip, bolt dia)."""
    from scipy.spatial import cKDTree
    if not len(C):
        return []
    mid = C + A * D[:, None] / 2
    # A corrupt decoded hole can be finite but astronomically far away; cKDTree
    # rejects it (and scipy may overflow while subtracting two such points).
    # These cannot be credible bolt stacks in an architectural steel job.
    valid = np.isfinite(mid).all(axis=1) & np.isfinite(A).all(axis=1) & np.isfinite(D) & np.isfinite(T) \
        & (np.abs(mid).max(axis=1) < 1e7) & (D > 0) & (D < 1e4)
    if not valid.any():
        return []
    C, A, D, T, I, mid = (x[valid] for x in (C, A, D, T, I, mid))
    tree = cKDTree(mid); used = np.zeros(len(C), bool); out = []
    for i in range(len(C)):
        if used[i]: continue
        cand = [j for j in tree.query_ball_point(mid[i], 6.0) if not used[j] and abs(abs(A[j] @ A[i]) - 1) < 1e-3]
        g = [j for j in cand if np.linalg.norm(np.cross(mid[j] - mid[i], A[i])) < 1 / 16 and abs(T[j] - T[i]) < 1e-3]
        used[g] = True
        if len({I[j] for j in g}) < 2 or not 0.2 <= T[i] <= 2.0: continue
        a = A[i]; s = [(C[j] - C[i]) @ a for j in g] + [(C[j] + A[j] * D[j] - C[i]) @ a for j in g]
        out.append((C[i] + a * min(s), a, max(s) - min(s), float(T[i])))
    return out


def main():
    convert(sys.argv[1], sys.argv[2])


USE_DERIVED_HOLES = True   # v5.4: holes where a decoded bolt crosses a piece that has no hole there (see below)
DERIVED_INFO = {}


def derive_bolt_holes(job, todo, hw, shared_inst, stats, skip_keys=frozenset()):
    """Bolt-derived holes (v5.4). Main members carry no hole records of their own (7.2/7.3: their piece files hold
    0-diameter markers; the member-file 658-B blocks are bolt records). For every decoded bolt - an SDS2 bolt record
    or a stack of >= 2 coaxial decoded holes - each exact placed piece whose own material the bolt line crosses between
    the head and head + grip gets a hole over that material span, unless it already has a decoded hole there. The
    diameter is copied from a coaxial decoded (round) hole of the same bolt; with none, nothing is cut and the case is
    listed. Holes are cut into the shared part (identical pieces share piece ids, so their holes coincide).
    Returns dict(derived_by_piece, not_cut (reason counts), examples, parts) and replaces cut parts in shared_inst."""
    from scipy.spatial import cKDTree
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Lin, gp_Pnt, gp_Dir
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    out = dict(derived_by_piece={}, not_cut=collections.Counter(), not_cut_examples=[], bolts_checked=0)
    # decoded holes, world: entry C, direction A (into the material), depth D, hole dia HD, slot SL
    if hw:
        HC = np.array([h[0] for h in hw]); HA = np.array([h[1] for h in hw]); HD = np.array([h[5] for h in hw])
        HSL = np.array([h[6] for h in hw]); hmid = HC + HA * np.array([h[2] for h in hw])[:, None] / 2
        htree = cKDTree(hmid)
    else:
        htree = None
    # exact part instances (shared): local solid (mm) + (R, t) with world_in = t + R @ local_in
    inst = []
    loc_box = {}
    for k, (key, local, trsf, label) in enumerate(shared_inst):
        if isinstance(key, tuple) or key in skip_keys:
            continue                                        # bolts, SDS2 bolt / nut / washer pieces, concrete
        R = np.array([[trsf.Value(r, c) for c in (1, 2, 3)] for r in (1, 2, 3)])
        t = np.array([trsf.Value(r, 4) for r in (1, 2, 3)]) / MM
        if key not in loc_box:
            b = Bnd_Box(); BRepBndLib.Add_s(local, b)
            lo, hi = b.CornerMin(), b.CornerMax()
            loc_box[key] = np.array([[lo.X(), lo.Y(), lo.Z()], [hi.X(), hi.Y(), hi.Z()]]) / MM
        lb = loc_box[key]
        corners = np.array([[x, y, z] for x in lb[:, 0] for y in lb[:, 1] for z in lb[:, 2]])
        W = corners @ R.T + t
        inst.append((key, local, R, t, W.min(0), W.max(0), k))
    if not inst:
        return out
    cell = 24.0
    grid = collections.defaultdict(list)
    for i, (_, _, _, _, lo, hi, _) in enumerate(inst):
        a0 = np.floor(lo / cell).astype(int); a1 = np.floor(hi / cell).astype(int)
        if np.prod(a1 - a0 + 1) > 4000:
            continue                                        # absurdly large part: not a bolted ply
        for gx in range(a0[0], a1[0] + 1):
            for gy in range(a0[1], a1[1] + 1):
                for gz in range(a0[2], a1[2] + 1):
                    grid[(gx, gy, gz)].append(i)
    inter = {}; clas = {}
    holes_local = collections.defaultdict(list)             # part key -> [hole dict (local inches)]
    for (e, a, grip, d, L, ty, src) in todo:
        e = np.asarray(e, float); a = np.asarray(a, float)
        if not (np.isfinite(e).all() and np.isfinite(a).all()) or not 0.05 < grip < 24:
            continue
        out["bolts_checked"] += 1
        # diameter: coaxial decoded round holes of this bolt
        dia = None
        if htree is not None:
            mid = e + a * grip / 2
            cand = htree.query_ball_point(mid, grip / 2 + 1.0)
            ds = [HD[j] for j in cand if abs(abs(HA[j] @ a) - 1) < 1e-3 and np.linalg.norm(np.cross(hmid[j] - e, a)) < 1 / 16
                  and HSL[j] <= 0 and 0 < HD[j] < 4]
            if ds:
                dia = float(min(ds))
        seg_lo = np.minimum(e, e + a * grip) - 0.5; seg_hi = np.maximum(e, e + a * grip) + 0.5
        cands = set()
        g0 = np.floor(seg_lo / cell).astype(int); g1 = np.floor(seg_hi / cell).astype(int)
        for gx in range(g0[0], g1[0] + 1):
            for gy in range(g0[1], g1[1] + 1):
                for gz in range(g0[2], g1[2] + 1):
                    cands.update(grid.get((gx, gy, gz), ()))
        for i in cands:
            key, local, R, t, lo, hi, k = inst[i]
            if np.any(seg_hi < lo) or np.any(seg_lo > hi):
                continue
            p0 = R.T @ (e - t); u = R.T @ a                  # local inches
            if key not in inter:
                inter[key] = IntCurvesFace_ShapeIntersector(); inter[key].Load(local, 1e-4)
                clas[key] = BRepClass3d_SolidClassifier(local)
            it = inter[key]
            try:
                it.Perform(gp_Lin(gp_Pnt(*(p0 * MM)), gp_Dir(*u)), -0.5 * MM, (grip + 0.5) * MM)
            except Exception:
                continue
            ts = sorted({round(it.WParameter(j) / MM, 5) for j in range(1, it.NbPnt() + 1)})
            spans = []
            for t0, t1 in zip(ts, ts[1:]):
                if t1 - t0 < 0.05:
                    continue
                mpt = p0 + u * (t0 + t1) / 2
                clas[key].Perform(gp_Pnt(*(mpt * MM)), 1e-3)
                if clas[key].State() == TopAbs_IN and t1 > 0.02 and t0 < grip - 0.02:
                    spans.append((max(t0, -0.05), min(t1, grip + 0.05)))
            for t0, t1 in spans:
                c_loc = p0 + u * t0
                # already a decoded hole here (piece-file hole, coaxial)?
                have = False
                for h in HOLES.get((job, key), ()):
                    if abs(abs(np.asarray(h["axis"]) @ u) - 1) < 1e-3 and np.linalg.norm(np.cross(np.asarray(h["c"]) - p0, u)) < 1 / 16:
                        have = True; break
                if have:
                    continue
                if dia is None:
                    out["not_cut"]["bolt without a coaxial decoded round hole (diameter unknown)"] += 1
                    if len(out["not_cut_examples"]) < 200:
                        out["not_cut_examples"].append(dict(piece=key, bolt_head=np.round(e, 3).tolist(), src=src))
                    continue
                hl = dict(c=c_loc, axis=-u, depth=t1 - t0, dia=dia, bolt=d, slot=0.0, ang=0.0, R=np.eye(3), type=0)
                if not any(np.linalg.norm(x["c"] - c_loc) < 0.01 and abs(x["axis"] @ hl["axis"]) > 0.999 for x in holes_local[key]):
                    holes_local[key].append(hl)
    # decoded piece-file holes that no bolt (record or >= 2-ply stack) passes through: their bolt continues into an
    # adjoining piece that SDS2 did not store a hole for (single shear tab / clip angle on a web). By rule nothing is
    # extended into that piece; the holes are counted and listed so the gap is visible.
    if htree is not None and todo:
        BE = np.array([np.asarray(t_[0], float) for t_ in todo]); BA = np.array([np.asarray(t_[1], float) for t_ in todo])
        BG = np.array([float(t_[2]) for t_ in todo])
        ok_ = np.isfinite(BE).all(1) & np.isfinite(BA).all(1) & np.isfinite(BG)
        btree = cKDTree(BE[ok_] + BA[ok_] * BG[ok_, None] / 2) if ok_.any() else None
        BEo, BAo, BGo = BE[ok_], BA[ok_], BG[ok_]
        single = 0
        for j in range(len(hmid)):
            covered = False
            if btree is not None:
                for i in btree.query_ball_point(hmid[j], 13.0):
                    if abs(abs(BAo[i] @ HA[j]) - 1) < 1e-3 and np.linalg.norm(np.cross(hmid[j] - BEo[i], BAo[i])) < 1 / 16:
                        covered = True; break
            if not covered:
                single += 1
                if len(out["not_cut_examples"]) < 400:
                    out["not_cut_examples"].append(dict(piece=int(hw[j][7]), hole_world=np.round(hmid[j], 3).tolist(),
                                                        reason="single-ply"))
        if single:
            out["not_cut"]["decoded hole with no bolt record or >= 2-ply stack: adjoining piece not drilled (rule)"] = single
    elif htree is not None:
        out["not_cut"]["decoded hole with no bolt record or >= 2-ply stack: adjoining piece not drilled (rule)"] = len(hmid)
    # cut, once per part, and swap the cut solid into every instance of that part
    cut_of = {}
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID

    def nsol(sh_):
        ex_ = TopExp_Explorer(sh_, TopAbs_SOLID); k_ = 0
        while ex_.More(): k_ += 1; ex_.Next()
        return k_
    for key, H in holes_local.items():
        local = next(x[1] for x in inst if x[0] == key)
        n0 = nsol(local)
        cut = brep.cut_holes(local, H)
        if cut is not local and nsol(cut) > n0:
            # a derived hole that splits the part (cylinder along an edge / through a thin tip) is not a real hole:
            # keep only the holes that cut cleanly one by one
            keep = []
            for h in H:
                c1 = brep.cut_holes(local, keep + [h])
                if c1 is not local and nsol(c1) == n0:
                    keep.append(h)
                else:
                    out["not_cut"]["derived hole would split the part"] += 1
            H = keep
            cut = brep.cut_holes(local, H) if H else local
        if cut is local:
            if H:
                out["not_cut"]["boolean failed (part left as decoded)"] += len(H)
            continue
        cut_of[key] = cut
        out["derived_by_piece"][key] = len(H)
        HOLES.setdefault((job, key), [])
        HOLES[(job, key)] = list(HOLES[(job, key)]) + H
    for k, (key, local, trsf, label) in enumerate(shared_inst):
        if key in cut_of:
            shared_inst[k] = (key, cut_of[key], trsf, label)
    stats["holes_derived"] = sum(out["derived_by_piece"].values())
    stats["pieces_with_derived_holes"] = len(out["derived_by_piece"])
    stats["holes_not_derived"] = sum(out["not_cut"].values())
    return out


def _absurd(sh, limit_in=2e5):
    """Solid larger than ~3 miles in any direction: corrupt source numbers, never real steel (no stored length or
    section is that large). A shared exact part ("shared", local solid, placement) is measured on its local solid: a
    rigid placement keeps its size. v5-v5.4.1 handed the shared tuple itself to the bounding box, which raised and
    counted as absurd, so exact bars, rods and rebar on the special-piece path (SB1/2, RB*, #-bars, couplers) were
    dropped as absurd_extent_corrupt_source_geometry: 5,076 pieces on 13 jobs (data-3 Edge_West 7.711: 1,504
    square-bar balusters, 905 x 13 x 13 mm, that v4c wrote and the job's IFC holds)."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    if isinstance(sh, tuple):
        sh = sh[1]
    try:
        b = Bnd_Box(); BRepBndLib.Add_s(sh, b)
        lo, hi = b.CornerMin(), b.CornerMax()
        ext = max(hi.X() - lo.X(), hi.Y() - lo.Y(), hi.Z() - lo.Z()) / MM
        return not np.isfinite(ext) or ext > limit_in
    except Exception:
        return True


def _tag(label, why):
    """Stand-in marker appended to a STEP product name: everything not exact is named so."""
    return f"{label} [approx: {why}]" if why else label


def _local_prism(loop, e, holes=()):
    return prism([np.asarray(q, float) for q in loop], np.asarray(e, float), [[np.asarray(q, float) for q in h] for h in holes])


def _place(sh, M, o):
    """Local solid -> world (o + M.T @ local); None if M is not a rotation or no valid placed form exists."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.ShapeFix import ShapeFix_Shape
    t = placement(M, o)
    if t is None or sh is None:
        return None
    w = BRepBuilderAPI_Transform(sh, t, True).Shape()
    if BRepCheck_Analyzer(w).IsValid():
        return w
    fx = ShapeFix_Shape(w); fx.Perform()
    return fx.Shape() if BRepCheck_Analyzer(fx.Shape()).IsValid() else None


def table_standin(V, p, sh_):
    """Last-resort local solid from the piece table when no builder works: plate -> L x W x T slab, rolled -> the
    nominal section over L. Positioned on the piece's vertex box when it has one (else from the piece origin)."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    L, W, Tk = p.get("L", 0), p.get("W", 0), p.get("T", 0)
    if sh_ is not None and L > 0 and sh_.d > 0:
        loops = T.profile(sh_)
        if loops:
            VV = np.array([[x, y, z] for x in (0.0, L) for y in (0.0, -sh_.d) for z in (-sh_.bf / 2, sh_.bf / 2)])
            if V is not None and len(V) >= 2 and np.ptp(V[:, 0]) > 0.5 * L:
                VV[:, 0] = np.where(VV[:, 0] == 0, V[:, 0].min(), V[:, 0].min() + L)
            loc = rolled_local(VV, sh_, L)
            if loc is not None:
                return _local_prism(*loc)
    dims = sorted([d for d in (L, W, Tk) if d > 0], reverse=True)
    if len(dims) < 3:
        return None
    if V is not None and len(V) >= 2:
        lo = V.min(0); ext = np.ptp(V, 0)
        order = np.argsort(-ext)                       # longest vertex extent gets the longest table dimension
        size = np.zeros(3)
        for k, d in zip(order, dims): size[k] = d
    else:
        lo = np.zeros(3); size = np.array(dims)
    try:
        return BRepPrimAPI_MakeBox(gp_Pnt(*(lo * MM)), *(size * MM)).Shape()
    except Exception:
        return None


def reset():
    """Clear per-job caches before converting again in the same process (read-back repair pass)."""
    for c in (_BREP, HOLES, BREP_WHY, _REF):
        c.clear()
    REF_OPEN.clear(); DERIVED_INFO.clear()
    CONCRETE.clear(); HOLES_NOT_CUT.clear(); HOLES_CUT.clear(); del INVALID_DROPPED[:]


def convert(job, out, shared=True):
    """shared=True: exact pieces are written once and placed per instance (STEP assembly); False: one copy each.
    v5: every part that is not SDS2's exact piece geometry is written with an `[approx: ...]` name suffix and listed
    in <out>_manifest.json (real type + reason); joists without pieces become open-web stand-ins; phantom material
    blocks are ignored; a piece placed identically by two non-twin members is written once (FIX item 12)."""
    global SHARED
    SHARED = shared
    import joist as J
    import manifest as MF
    from instances import piece_vertices
    pieces = read_pieces(job); shapes = read_shapes(job)
    mems, _ = read_members(job)
    mtype = {m.id: m.type for m in mems}
    mem_by_id = {m.id: m for m in mems}
    sig = {m.id: (m.type, m.section.name if m.section else None, tuple(np.round(m.p1, 2)), tuple(np.round(m.p2, 2)))
           for m in mems}
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    rows = []; skipped_rows = []; dup_rows = []
    stats = {"plate": 0, "rolled": 0, "skipped": 0, "member_fallback": 0, "exact": 0}
    instance_counts = collections.Counter()
    skipped = collections.Counter()
    written = {}                                # (piece, origin, rotation) -> (member, row index): FIX item 12
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    wsum = [0.0, 0.0]; wcache = {}; wdiff = collections.Counter()
    fam_w = collections.defaultdict(lambda: [0.0, 0.0, 0])
    env_w = [0.0]; big = []

    def track(sid, sh, how):
        """Steel weight of the placed solid vs SDS2's piece weight (concrete excluded), one volume per piece build."""
        p = pieces[sid]
        if p["name"].startswith("Conc") or not 0 < p["wt"] < 1e6:          # corrupt weights (Centene: 3e311 lb)
            return
        if re.match(r"G[TR]\d", p["name"]):
            return        # bar grating: SDS2 weighs the open mesh, the solid panel is ~7x that (SampleJob, Centene)
        if (sid, how) not in wcache:
            g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); wcache[(sid, how)] = abs(g.Mass()) / MM ** 3 * 0.2836
        if not np.isfinite(wcache[(sid, how)]) or wcache[(sid, how)] > 1e7 or p["wt"] < 1e-3:
            return        # corrupt geometry / weight (run-2 GHTUG canary: steel ratio 2.8e214) stays out of the tally
        wsum[0] += wcache[(sid, how)]; wsum[1] += p["wt"]
        wdiff[(sid, p["name"], how)] += wcache[(sid, how)] - p["wt"]
        big.append((wcache[(sid, how)] - p["wt"], p["wt"], p["name"], sid))
        f = MF.family(p["name"]); fw = fam_w[f]
        fw[0] += wcache[(sid, how)]; fw[1] += p["wt"]; fw[2] += 1

    def record_skip(n, sid, inst_no, p, k, origin, reason):
        stats["skipped"] += 1
        skipped[p["name"][:12]] += 1
        skipped_rows.append(dict(member=n, member_type=mtype[n], piece=sid, inst=inst_no,
                                 name=p["name"], kind=k, reason=reason,
                                 ox=round(origin[0], 4), oy=round(origin[1], 4), oz=round(origin[2], 4)))

    def add_row(row, dkey=None, label="", standin="", real=""):
        row.update(label=label, standin=standin, real_type=real if standin else "", also_on_member="")
        rows.append(row)
        if dkey is not None:
            written.setdefault(dkey, (row["member"], len(rows) - 1))

    parts = {}; root = [None]; hw = []          # hw: placed holes (entry, axis, depth, bolt dia, instance)
    shared_inst = []                            # (part key, local solid, placement, instance label)
    frames = {}                                 # member -> main material placement (bolt record frame)
    bolt_rows = []

    def add_exact(sid, res, label):
        """Write an exact piece: shared mode -> one part per piece + a located component per instance under the job
        assembly; flat mode -> the placed copy. Returns the (local or placed) solid for the weight tally."""
        if isinstance(res, tuple):
            _, local, trsf = res
            shared_inst.append((sid, local, trsf, label))           # written at the end, after the part check
            return local
        lab = st.AddShape(res, False)
        TDataStd_Name.Set_s(lab, TCollection_ExtendedString(label))
        return res

    def add_flat(sh, label):
        if label in DROP_LABELS:
            INVALID_DROPPED.append(label); return
        lab = st.AddShape(sh, False)
        TDataStd_Name.Set_s(lab, TCollection_ExtendedString(label))

    n_members_without_geometry = 0
    from sds2job import REFERENCE_TYPES
    ref_pieces = None
    for n in sorted(mtype):
        if mtype[n] == "Ref Point":
            continue
        if mtype[n] in REFERENCE_TYPES:
            # imported reference model: its piece files have no piece-table entry; place SDS2's stored B-rep of each
            # (no weight to check against, never approximated: a part whose faces don't close is left out)
            if ref_pieces is None:
                ids_ = [int(x) for x in os.listdir(os.path.join(job, "subm")) if x.isdigit()]
                ref_pieces = {i: pieces.get(i) or dict(name="REFERENCE", sec=0, L=0, W=0, T=0, wt=0) for i in ids_}
            _, rinst = material_instances(job, n, ref_pieces)
            stats["reference_members"] = stats.get("reference_members", 0) + 1
            stats["reference_placements"] = stats.get("reference_placements", 0) + len(rinst)
            if not rinst:
                from instances import count_frames
                try:
                    stats["reference_unlinked_frames"] = stats.get("reference_unlinked_frames", 0) + count_frames(job, n)
                except OSError:
                    pass
            import time as _t
            t_ref = _t.time()
            for sid, M, o in rinst:
                if _t.time() - t_ref > REF_BUDGET_S and (job, sid) not in _REF:
                    # bounded: imported meshes can hold tens of thousands of faceted parts (pp3: 78k files)
                    instance_counts[(n, sid)] += 1
                    record_skip(n, sid, instance_counts[(n, sid)], ref_pieces[sid], "reference", o, "reference_time_budget_exceeded")
                    continue
                p = ref_pieces[sid]
                if sid in pieces and pieces[sid]["wt"] > 0:
                    continue                            # named SDS2 pieces placed by the model: handled below if listed
                instance_counts[(n, sid)] += 1; inst_no = instance_counts[(n, sid)]
                sh = brep_reference(job, sid, M, o)
                if sh is None:
                    record_skip(n, sid, inst_no, p, "reference", o, "reference_part_no_closed_brep"); continue
                opn = (job, sid) in REF_OPEN
                label = (f"{mtype[n]} #{n} / reference part (piece {sid}, inst {inst_no}) [reference: imported model geometry "
                         f"as stored by SDS2, not fabricated steel{'; open surface, not a closed solid' if opn else ''}]")
                add_exact(sid, sh, label)
                stats["reference_parts"] = stats.get("reference_parts", 0) + 1
                if opn:
                    stats["reference_open_shells"] = stats.get("reference_open_shells", 0) + 1
                add_row(dict(member=n, member_type=mtype[n], piece=sid, inst=inst_no, name=p["name"], kind="reference",
                             builder="reference_brep", ox=round(o[0], 4), oy=round(o[1], 4), oz=round(o[2], 4)),
                        label=label)
            continue
        main_sid, inst = material_instances(job, n, pieces)
        for sid_, M_, o_ in inst:
            if sid_ == main_sid:
                frames[n] = (M_, o_); break
        if not inst:
            m = mem_by_id[n]
            if mtype[n] not in T.STRUCTURAL:
                n_members_without_geometry += 1
                continue
            sec = m.section.name if m.section else ""
            sh = None
            if T.is_joist(m):
                # SDS2 7.0-7.6: vendor joists are members with a designation only (FIX item 1): open-web stand-in
                wt, basis = J.typical_weight(sec, m.section.d, m.section.weight)
                sh, info = J.joist_solid(m, wt)
                if sh is not None:
                    label = _tag(f"{m.type} #{n} / {sec} (joist stand-in)",
                                 f"derived_from_designation open-web joist {info['chord_angle']} chords + {info['web_bar_dia']:g} in web bars, "
                                 f"{wt:g} lb/ft ({basis}); SDS2 stores only the designation")
                    builder, why = "joist_openweb_standin", f"derived_from_designation: open-web joist sized to {wt:g} lb/ft ({basis}); no chord/web data in the job"
                    real = f"open-web steel joist {sec} (vendor-designed)"
                    stats["joist_standin"] = stats.get("joist_standin", 0) + 1
                    env_w[0] += wt * np.linalg.norm(np.subtract(m.p2, m.p1)) / 12
            if sh is None:
                sh = T.solid_for(m, "X", 1)
                if sh is None:
                    n_members_without_geometry += 1
                    if T.is_joist(m):
                        # never silent (v5.2-v5.4.1 dropped 50 DSLH joists without a trace): list it as not built
                        skipped_rows.append(dict(member=n, member_type=m.type, piece=0, inst=0, name=sec, kind="member",
                                                 reason="joist_without_depth",
                                                 ox=round(m.p1[0], 4), oy=round(m.p1[1], 4), oz=round(m.p1[2], 4)))
                        stats["skipped"] += 1
                    continue
                why = "member work-line envelope: the job has no fabricated pieces for this member"
                if m.section is not None and m.section.name in T.PROFILE_NOTES:
                    why += f"; {T.PROFILE_NOTES[m.section.name]} (real section dimensions not in the job)"
                label = _tag(f"{m.type} #{n} / {sec} (member envelope)", why)
                builder, real = ("joist_envelope_approx", f"open-web steel joist {sec}") if m.type == "JOIST" else \
                    ("member_envelope", f"{m.type} {sec}")
                if m.type == "JOIST":
                    stats["joist_envelope"] = stats.get("joist_envelope", 0) + 1
            add_flat(sh, label)
            stats["member_fallback"] += 1
            add_row(dict(member=n, member_type=m.type, piece=0, inst=0, name=sec, kind="member", builder=builder,
                         ox=round(m.p1[0], 4), oy=round(m.p1[1], 4), oz=round(m.p1[2], 4)),
                    label=label, standin=why, real=real)
            continue
        for sid, M, o in inst:
            p = pieces[sid]; k = kind(p)
            instance_counts[(n, sid)] += 1
            inst_no = instance_counts[(n, sid)]
            label = piece_instance_label(mtype[n], n, p["name"], sid, inst_no)
            # 0.1 in origin grid: the two members of a connection can store the same piece 0.005-0.01 in apart
            # (AGNEWS-R 7.331: bolt pieces at z -14.87 / -14.88), which a 0.01 grid split
            dkey = (sid, tuple(np.round(o, 1)), tuple(np.round(M, 2).ravel()))
            prev = written.get(dkey)
            if prev is not None and prev[0] != n and sig.get(prev[0]) != sig.get(n):
                # the same piece at the same place, listed by both members of a connection (FIX item 12): write once
                r0 = rows[prev[1]]
                r0["also_on_member"] = (r0["also_on_member"] + ";" if r0["also_on_member"] else "") + str(n)
                dup_rows.append(dict(member=n, piece=sid, inst=inst_no, name=p["name"], written_with_member=prev[0]))
                stats["duplicate_skipped"] = stats.get("duplicate_skipped", 0) + 1
                continue
            # exact B-rep: plates / rolled / joists, and bolts (SDS2 stores each nut, head and washer as its own
            # faceted hex / ring piece). Studs and rods keep the true cylinders of special_solid; concrete its prism.
            if (k in ("plate", "rolled") and not TURNED.match(p["name"]) or p["name"].startswith("BLT")) \
                    and not p["name"].startswith("Conc"):
                sh = brep_placed(job, sid, p, M, o)
                if sh is not None:
                    conc = (job, sid) in CONCRETE
                    k2 = "concrete" if conc else "fastener" if p["name"].startswith("BLT") else k
                    notes = []
                    if (job, sid) in HOLES_NOT_CUT:
                        notes.append("bolt holes decoded but not cut")
                    if re.match(r"G[TR]\d", p["name"]):
                        notes.append("bar grating written as SDS2's solid panel (open mesh not modelled)")
                    lab_ = _tag(label, "; ".join(notes))
                    sh = add_exact(sid, sh, lab_)
                    for h in HOLES.get((job, sid), ()) if USE_BOLTS else ():
                        hw.append((o + M.T @ h["c"], -(M.T @ h["axis"]), h["depth"], h["bolt"], len(rows), h["dia"], h["slot"], sid))
                    stats[k2] = stats.get(k2, 0) + 1; stats["exact"] += 1
                    stats["exact_brep"] = stats.get("exact_brep", 0) + 1
                    if not conc: track(sid, sh, "exact")
                    add_row(dict(member=n, member_type=mtype[n], piece=sid, inst=inst_no,
                                 name=p["name"], kind=k2, builder="exact_brep",
                                 ox=round(o[0], 4), oy=round(o[1], 4), oz=round(o[2], 4)), dkey,
                            label=lab_, standin="; ".join(notes),
                            real=("bar grating" if re.match(r"G[TR]\d", p["name"]) else p["name"]))
                    continue
            exact_why = BREP_WHY.get((job, sid)) or ("approximate builders requested (--approx)" if not USE_BREP else
                                                     "piece has no SDS2 weight to validate its B-rep")
            if k == "rolled" and J.is_joist_section(p["name"]) and p.get("L", 0) > 0:
                # 7.7+/8.0 joist pieces whose multi-body B-rep does not close (TYSONS 7.720: 20 joists): open-web joist
                # derived from the designation over the piece's own length, placed on its vertex box (top at max y)
                Vj = piece_vertices(job, sid)
                sh_ = shapes.get(p["sec"])
                depth = sh_.d if sh_ is not None and sh_.d > 0 else (float(J.DESIG.match(p["name"]).group(1)) if J.DESIG.match(p["name"]) else 0)
                if Vj is not None and len(Vj) >= 4 and depth > 0:
                    wt_j, basis_j = J.typical_weight(p["name"], depth, 0)
                    try:
                        loc_j, info_j = J.joist_local(depth, float(np.ptp(Vj[:, 0])) or p["L"], wt_j)
                        from OCP.gp import gp_Trsf
                        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
                        tj = gp_Trsf(); tj.SetTranslation(gp_Vec(Vj[:, 0].min() * MM, Vj[:, 1].max() * MM, Vj[:, 2].mean() * MM))
                        shj = _place(BRepBuilderAPI_Transform(loc_j, tj, True).Shape(), M, o)
                    except Exception:
                        shj = None
                    if shj is not None:
                        why = (f"derived_from_designation open-web joist {info_j['chord_angle']} chords + {info_j['web_bar_dia']:g} in "
                               f"web bars, {wt_j:g} lb/ft ({basis_j}); SDS2's own joist B-rep not usable ({exact_why})")
                        lab_ = _tag(label, why)
                        add_flat(shj, lab_)
                        stats["joist_standin"] = stats.get("joist_standin", 0) + 1
                        add_row(dict(member=n, member_type=mtype[n], piece=sid, inst=inst_no, name=p["name"], kind="rolled",
                                     builder="joist_openweb_standin", ox=round(o[0], 4), oy=round(o[1], 4), oz=round(o[2], 4)),
                                dkey, label=lab_, standin=why, real=f"open-web steel joist {p['name']}")
                        continue
            V = piece_vertices(job, sid) if k in ("plate", "rolled") and not TURNED.match(p["name"]) else subm_vertices(job, sid)
            if (V is None or len(V) < 4) and k in ("plate", "rolled") and not TURNED.match(p["name"]) \
                    and not p["name"].startswith("Conc"):
                V = mesh_vertices(job, sid)        # no tagged outline: use the piece's mesh vertices instead
            nominal = False
            if (V is None or len(V) < 4) and k == "rolled" and p["sec"] in shapes and p["L"] > 0:
                # piece file holds no geometry (e.g. 216-B stubs on 7.516 HENRY FORD): nominal straight piece,
                # section over its length, top of section at local y = 0 like the decoded rolled pieces
                s_ = shapes[p["sec"]]
                V = np.array([[x, y, z] for x in (0.0, p["L"]) for y in (0.0, -s_.d) for z in (-s_.bf / 2, s_.bf / 2)])
                nominal = True
            if V is None or len(V) < 4 or k == "other" or TURNED.match(p["name"]) or p["name"].startswith("Conc"):
                # weld studs, bolts, anchor rods, concrete: built from their mesh / piece-table dimensions
                sh, k2 = special_solid(job, sid, p, M, o)
                builder = "special_primitive"
                if sh is None and not p["name"].startswith("Conc"):
                    # e.g. threaded studs with no rings; square / round bars and rebar keep their table kind
                    sh, k2 = brep_placed(job, sid, p, M, o), ("fastener" if TURNED.match(p["name"]) else k)
                    if sh is not None:
                        stats["exact"] += 1
                        builder = "exact_brep"
                why = ""
                if sh is None and k in ("plate", "other"):
                    loc_sh = table_standin(V, p, None)
                    sh = _place(loc_sh, M, o)
                    if sh is not None:
                        builder, k2 = "piece_table_standin", ("plate" if k == "plate" else "other")
                        why = f"L x W x T slab from the piece table ({exact_why}; no usable vertices)"
                if sh is None:
                    record_skip(n, sid, inst_no, p, k, o, "no_usable_special_geometry")
                    continue
                if builder == "special_primitive" and p["name"].startswith("Conc"):
                    why = "concrete as its L x W x T prism at the bottom of its mesh (volume = SDS2 quantity)"
                elif builder == "special_primitive" and SPECIAL_NOTE:
                    why = SPECIAL_NOTE
                if sh is not None and _absurd(sh):
                    record_skip(n, sid, inst_no, p, k, o, "absurd_extent_corrupt_source_geometry")
                    continue
                lab_ = _tag(label, why)
                sh = add_exact(sid, sh, lab_)
                stats[k2] = stats.get(k2, 0) + 1; track(sid, sh, k2)
                stats[builder] = stats.get(builder, 0) + 1
                add_row(dict(member=n, member_type=mtype[n], piece=sid, inst=inst_no,
                             name=p["name"], kind=k2, builder=builder,
                             ox=round(o[0], 4), oy=round(o[1], 4), oz=round(o[2], 4)), dkey,
                        label=lab_, standin=why, real=p["name"])
                continue
            bent = False
            if k == "plate":
                loc = plate_local(V, p)
                bent = loc is not None and p["T"] > 0 and np.ptp(V, 0).min() > 1.5 * p["T"] + 0.05
            elif k == "rolled" and p["sec"] in shapes:
                loc = rolled_local(V, shapes[p["sec"]], p["L"])
            else:
                loc = None
            builder = "profile_fallback" if k == "rolled" else ("bent_plate_fallback" if bent else "plate_fallback")
            if loc is None and k == "rolled" and V is not None and len(V) >= 4 and np.ptp(V[:, 0]) > 0:
                # section record without dimensions (8.007 joists: 30K11 has d = bf = 0): envelope box of the
                # piece's own vertices along local x, like the joist envelopes elsewhere
                lo_, hi_ = V.min(0), V.max(0)
                loc = ([np.array([lo_[0], y, z]) for y, z in ((lo_[1], lo_[2]), (hi_[1], lo_[2]), (hi_[1], hi_[2]), (lo_[1], hi_[2]))],
                       np.array([hi_[0] - lo_[0], 0.0, 0.0]))
                builder = "vertex_box_fallback"
            sh = None
            if loc is not None:
                sh = _local_prism(loc[0], loc[1], loc[2] if len(loc) > 2 else [])
                if sh is None and k == "plate":
                    # refined outline (bent / concave) rejected: fall back to the plain convex-hull plate
                    loc2 = plate_local(V)
                    if loc2 is not None:
                        sh = _local_prism(loc2[0], loc2[1]); builder = "plate_hull_fallback"
            if sh is None and k == "rolled" and sid == main_sid and mem_by_id[n].section is not None:
                # main material stored as a flat 2D outline (zero extent along local x; 7.613 Building_101j W10x26):
                # use the member's own stage-1 solid, oriented from its end points and roll
                shw = T.solid_for(mem_by_id[n], "X", 1)
                if shw is not None:
                    why = f"member work-line envelope for the main material ({exact_why})"
                    if mem_by_id[n].section.name in T.PROFILE_NOTES:
                        why += f"; {T.PROFILE_NOTES[mem_by_id[n].section.name]}"
                    lab_ = _tag(label, why)
                    add_flat(shw, lab_)
                    stats["member_fallback"] += 1
                    add_row(dict(member=n, member_type=mtype[n], piece=sid, inst=inst_no,
                                 name=p["name"], kind="member", builder="member_envelope",
                                 ox=round(o[0], 4), oy=round(o[1], 4), oz=round(o[2], 4)), dkey,
                            label=lab_, standin=why, real=p["name"])
                    continue
            if sh is None:
                sh = table_standin(V, p, shapes.get(p["sec"]) if k == "rolled" else None)
                if sh is not None:
                    builder = "piece_table_standin"
            holes_txt = "no holes"
            if sh is not None and USE_HOLES and builder != "piece_table_standin":
                # cut the piece's own decoded holes into the approximate solid too (FIX item 8)
                try:
                    H = brep.holes(open(os.path.join(job, "subm", str(sid)), "rb").read())
                except OSError:
                    H = []
                if H:
                    cut = brep.cut_holes(sh, H)
                    HOLES_CUT["holes (approximate pieces)" if cut is not sh else "holes not cut (approximate pieces)"] += len(H)
                    holes_txt = "holes cut" if cut is not sh else "holes decoded but not cut"
                    if cut is not sh:
                        HOLES[(job, sid)] = H
                    sh = cut
            placed = _place(sh, M, o)
            if placed is None and sh is not None:
                record_skip(n, sid, inst_no, p, k, o, "approx_solid_invalid_at_placement_or_bad_frame"); continue
            sh = placed
            skip_reason = "fallback_builder_failed"
            if sh is not None and 0 < p["wt"] < 1e6:
                # approximate solid wildly heavier than SDS2's weight (7.708 Center Grove: wall "plate" 7 5/8x384
                # whose vertices coincide -> mesh box of 50 million lb): report instead of writing it
                g_ = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g_); w_ = abs(g_.Mass()) / MM ** 3 * 0.2836
                if w_ > 5 * p["wt"] and w_ - p["wt"] > 1000:
                    sh = None
                    skip_reason = "fallback_over_5x_source_weight"
                    # v4 skipped these (CHOWNS 6.336: 34 bent plates whose convex hull fills the bend): write the
                    # piece-table slab instead, tagged as a stand-in
                    ts = _place(table_standin(V, p, shapes.get(p["sec"]) if k == "rolled" else None), M, o)
                    if ts is not None:
                        g2 = GProp_GProps(); BRepGProp.VolumeProperties_s(ts, g2)
                        if abs(g2.Mass()) / MM ** 3 * 0.2836 < 2 * p["wt"] + 1000:
                            sh, builder, holes_txt = ts, "piece_table_standin", "no holes"
            if sh is None:
                record_skip(n, sid, inst_no, p, k, o, skip_reason)
                continue
            what = {"profile_fallback": "section profile extruded over the piece's vertex length",
                    "plate_fallback": "plate outline from the piece's vertices extruded by its thickness",
                    "bent_plate_fallback": "bent plate end section extruded along the bend line",
                    "plate_hull_fallback": "convex-hull plate from the piece's vertices",
                    "vertex_box_fallback": "box of the piece's vertices (section without dimensions)",
                    "piece_table_standin": "piece-table size (L x W x T / nominal section)"}[builder]
            if nominal and builder == "profile_fallback":
                what = "nominal section over the piece-table length (piece file holds no geometry)"
            note = T.PROFILE_NOTES.get(shapes[p["sec"]].name) if k == "rolled" and p["sec"] in shapes else None
            why = f"{what}; copes/cuts not modelled; {holes_txt} ({exact_why})" + (f"; {note}" if note else "")
            lab_ = _tag(label, why)
            add_flat(sh, lab_)
            stats[k] += 1; track(sid, sh, "approx")
            stats[builder] = stats.get(builder, 0) + 1
            add_row(dict(member=n, member_type=mtype[n], piece=sid, inst=inst_no,
                         name=p["name"], kind=k, builder=builder,
                         ox=round(o[0], 4), oy=round(o[1], 4), oz=round(o[2], 4)), dkey,
                    label=lab_, standin=why, real=p["name"])
    if USE_BOLTS:
        # SDS2's own bolt records (bolts.py: head point, axis, diameter, length, grip, type) where the job has them;
        # nominal heavy-hex bolts only for coaxial hole stacks of >= 2 pieces that no record covers
        import bolts as BR
        recs = []
        for n in sorted(mtype):
            try: recs += BR.member_bolts(job, n, frames.get(n))
            except Exception: pass
        btype = BR.bolt_types(job)
        if recs:
            # the same bolt can be stored by both connected members: keep one per head point + axis
            from scipy.spatial import cKDTree
            hp = np.array([r["head"] for r in recs]); drop = set()
            for i, j in sorted(cKDTree(hp).query_pairs(1e-3)):
                if i not in drop and abs(abs(recs[i]["axis"] @ recs[j]["axis"]) - 1) < 1e-3: drop.add(j)
            recs = [r for k, r in enumerate(recs) if k not in drop]
        stacks = []
        if hw:
            C, A, D, Tb, I = (np.array([h[i] for h in hw]) for i in range(5))
            stacks = bolt_stacks(C, A, D, Tb, I)
        if any(r["layout"] == "f32" for r in recs):
            # 7.0xx / early 7.1xx records: only those landing on a decoded hole face are trusted (SUNY 7.021 has
            # many that don't, with no consistent offset); f64 records (7.1xx-8.0xx) are all kept
            from scipy.spatial import cKDTree
            face = cKDTree(np.vstack([C, C + A * D[:, None]])) if hw else None
            on = {id(r): face is not None and bool(np.isfinite(face.query(r["head"], distance_upper_bound=2e-3)[0]))
                  for r in recs if r["layout"] == "f32"}
            rate = sum(on.values()) / max(len(on), 1)
            stats["bolt_records_f32_on_holes"] = round(rate, 3)
            if rate < 0.35:
                # healthy jobs of every layout put 34-56 % of bolt heads on a decoded hole face (Merriam's two copies
                # agree bolt for bolt); far below that (SUNY 5.5 %, RCMS 22 %) only the validated ones are kept
                recs = [r for r in recs if r["layout"] == "f64" or on[id(r)]]
        covered = set()
        if recs and stacks:
            from scipy.spatial import cKDTree
            ends = [(e, si) for si, (e, a, g, d) in enumerate(stacks)] + [(e + a * g, si) for si, (e, a, g, d) in enumerate(stacks)]
            tree = cKDTree(np.array([x for x, _ in ends]))
            for r in recs:
                dist, j = tree.query(r["head"], distance_upper_bound=2e-3)
                if np.isfinite(dist): covered.add(ends[j][1])
        bparts = {}
        todo = [(r["head"], r["axis"], r["grip"], r["dia"], r["length"], btype.get(r["type"], ""), "sds2") for r in recs] + \
               [(e, a, g, d, None, "", "nominal") for si, (e, a, g, d) in enumerate(stacks) if si not in covered]
        for bolt_inst, (e, a, grip, d, L, ty, src) in enumerate(todo, 1):
            key = (round(d, 4), round(grip * 16) / 16, round(L * 16) / 16 if L else None)
            x = np.cross(a, [0, 0, 1.0] if abs(a[2]) < 0.9 else [1.0, 0, 0]); x /= np.linalg.norm(x); y = np.cross(a, x)
            t = placement(np.array([x, y, a]), e)
            if t is None: continue
            if key not in bparts:
                bparts[key] = bolt_local(key[0], key[1], key[2])
            lab = (f"BOLT {ty + ' ' if ty else ''}{d:g} x {L:g} (grip {grip:g})" if src == "sds2"
                   else f"BOLT {d:g} x {key[1]:g} grip (nominal heavy hex)") + f" (inst {bolt_inst})"
            if src == "nominal":
                lab = _tag(lab, "bolt guessed through a decoded hole stack: diameter and grip from the holes, "
                                "length / head side / washers not in the data")
                bolt_rows.append(lab)
            if SHARED:
                add_exact(("bolt",) + key, ("shared", bparts[key], t), lab)
            else:
                from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
                add_exact(None, BRepBuilderAPI_Transform(bparts[key], t, True).Shape(), lab)
            stats["bolts"] = stats.get("bolts", 0) + 1
            stats["bolts_" + src] = stats.get("bolts_" + src, 0) + 1
        if USE_HOLES and USE_DERIVED_HOLES and SHARED and todo:
            skip = {k for k in pieces if pieces[k]["name"].startswith(("BLT", "Conc")) or TURNED.match(pieces[k]["name"])
                    or (job, k) in CONCRETE}
            derived = derive_bolt_holes(job, todo, hw, shared_inst, stats, skip)
            DERIVED_INFO.update(derived)
    if shared_inst:
        # a few parts read back invalid once placed through an assembly location although the same solid is valid as a
        # placed copy (SCHUCKERS C12x20.7, PIPE 1 1/2: 6 of 288 parts); test each part once at its first placement
        # and write the instances of failing parts as placed copies
        first = {}
        for key, local, trsf, _ in shared_inst: first.setdefault(key, (local, trsf))
        # the temporary assembly STEP holds every unique part once more in memory; above ASSEMBLY_CHECK_MAX parts
        # (imported reference meshes: 12,000+) it is skipped - the --verify read-back repair pass covers those parts
        bad = assembly_check(first) if len(first) <= ASSEMBLY_CHECK_MAX else set()
        if len(first) > ASSEMBLY_CHECK_MAX:
            stats["assembly_check_skipped_parts"] = len(first)
        from OCP.TopLoc import TopLoc_Location
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        root[0] = st.NewShape()
        TDataStd_Name.Set_s(root[0], TCollection_ExtendedString(os.path.basename(job.rstrip("\\/"))))
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.ShapeFix import ShapeFix_Shape
        for key, local, trsf, label in shared_inst:
            if key in bad:
                lab = st.AddShape(BRepBuilderAPI_Transform(local, trsf, True).Shape(), False)
                TDataStd_Name.Set_s(lab, TCollection_ExtendedString(label)); continue
            if label in DROP_LABELS:
                stats["invalid_at_placement_dropped"] = stats.get("invalid_at_placement_dropped", 0) + 1
                INVALID_DROPPED.append(label); continue
            if label in FORCE_FLAT or (CHECK_PLACED and not isinstance(key, tuple)
                                       and not BRepCheck_Analyzer(local.Moved(TopLoc_Location(trsf))).IsValid()):
                # ~1 in 10,000 exact parts is valid locally but invalid at one of its placements; v4 wrote it and the
                # whole job was rejected on read-back (data-4: 13 jobs with 1-22 such solids). Write that instance as
                # a placed copy (ShapeFix if needed); if no form is valid, leave it out and report it.
                cp = BRepBuilderAPI_Transform(local, trsf, True).Shape()
                if not BRepCheck_Analyzer(cp).IsValid():
                    fx = ShapeFix_Shape(cp); fx.Perform(); cp = fx.Shape()
                if BRepCheck_Analyzer(cp).IsValid():
                    lab = st.AddShape(cp, False)
                    TDataStd_Name.Set_s(lab, TCollection_ExtendedString(label))
                    stats["placed_copy_for_validity"] = stats.get("placed_copy_for_validity", 0) + 1
                else:
                    stats["invalid_at_placement_dropped"] = stats.get("invalid_at_placement_dropped", 0) + 1
                    INVALID_DROPPED.append(label)
                continue
            if key not in parts:
                parts[key] = st.AddShape(local, False)
                pn = f"{pieces[key]['name']} (piece {key})" if key in pieces else label
                nd = DERIVED_INFO.get("derived_by_piece", {}).get(key)
                if nd:
                    pn += f" [derived: bolt record + coaxial hole: {nd} hole(s)]"
                TDataStd_Name.Set_s(parts[key], TCollection_ExtendedString(pn))
            comp = st.AddComponent(root[0], parts[key], TopLoc_Location(trsf))
            TDataStd_Name.Set_s(comp, TCollection_ExtendedString(label))
        stats["parts_written_flat"] = len(bad)
    if root[0] is not None:
        st.UpdateAssemblies()
        stats["unique_parts"] = len(parts)
    for lab_ in INVALID_DROPPED:
        mm = re.match(r"^(.+?) #(\d+) / (.*?) \(piece (\d+), inst (\d+)\)", lab_)
        if mm:
            skipped_rows.append(dict(member=int(mm.group(2)), member_type=mm.group(1), piece=int(mm.group(4)),
                                     inst=int(mm.group(5)), name=mm.group(3), kind="", reason="exact_solid_invalid_at_placement",
                                     ox="", oy="", oz=""))
            for r in rows:
                if r["member"] == int(mm.group(2)) and r["piece"] == int(mm.group(4)) and r["inst"] == int(mm.group(5)):
                    rows.remove(r); break
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    w = STEPCAFControl_Writer(); w.SetNameMode(True)
    w.Transfer(doc, STEPControl_AsIs)
    ok = w.Write(out) == IFSelect_RetDone
    base = os.path.splitext(out)[0]
    with open(base + "_pieces.csv", "w", newline="") as f:
        cw = csv.DictWriter(f, fieldnames=("member", "member_type", "piece", "inst", "name", "kind",
                                           "builder", "ox", "oy", "oz", "standin", "also_on_member"), extrasaction="ignore")
        cw.writeheader(); cw.writerows(rows)
    with open(base + "_skipped.csv", "w", newline="") as f:
        cw = csv.DictWriter(f, fieldnames=("member", "member_type", "piece", "inst", "name", "kind",
                                           "reason", "ox", "oy", "oz"))
        cw.writeheader(); cw.writerows(skipped_rows)
    print(f"version {read_version(job)}; solids: {stats}; write ok={ok} -> {out}")
    if wsum[1] > 0:
        print(f"  steel pieces: solids {wsum[0] / 2000:.1f} t vs SDS2 piece weights {wsum[1] / 2000:.1f} t "
              f"(ratio {wsum[0] / wsum[1]:.3f}; member envelopes not included)")
        if abs(wsum[0] / wsum[1] - 1) > 0.05:
            print("  largest differences (lb, piece, name, builder):",
                  [(round(v), s, nm, h) for (s, nm, h), v in sorted(wdiff.items(), key=lambda kv: -abs(kv[1]))[:3]])
    stats["steel_ratio"] = round(wsum[0] / wsum[1], 4) if wsum[1] else None
    if HOLES_CUT:
        print("  bolt holes (unique pieces):", dict(HOLES_CUT))
    if skipped:
        print("  not built (no usable geometry):", dict(skipped.most_common(10)))
    placed_total = sum(instance_counts.values())
    man = MF.build(job=job, out=out, version=read_version(job), stats=stats, rows=rows, skipped=skipped_rows,
                   dups=dup_rows, bolt_standins=bolt_rows, mems=mems, placed=placed_total,
                   members_without_geometry=n_members_without_geometry,
                   weights=dict(step_lb=wsum[0], sds2_lb=wsum[1], joist_standin_lb=env_w[0],
                                by_family={f: dict(step_lb=round(v[0], 1), sds2_lb=round(v[1], 1), n=v[2],
                                                   ratio=round(v[0] / v[1], 4) if v[1] else None)
                                           for f, v in sorted(fam_w.items(), key=lambda kv: -kv[1][1])}),
                   holes=dict(HOLES_CUT, derived=dict(holes=stats.get("holes_derived", 0),
                                                      pieces=stats.get("pieces_with_derived_holes", 0),
                                                      bolts_checked=DERIVED_INFO.get("bolts_checked", 0),
                                                      by_piece={str(k): v for k, v in DERIVED_INFO.get("derived_by_piece", {}).items()},
                                                      tag="derived: bolt record + coaxial hole"),
                              holes_not_cut=dict(by_reason=dict(DERIVED_INFO.get("not_cut", {})),
                                                 examples=DERIVED_INFO.get("not_cut_examples", []))),
                   write_ok=ok, piece_dev=big)
    MF.write(man, base + "_manifest.json")
    print(f"  manifest: class {man['class']} corpus {man['corpus']} ({'; '.join(man['class_reasons'][:4])})")
    return ok, stats


if __name__ == "__main__":
    main()
