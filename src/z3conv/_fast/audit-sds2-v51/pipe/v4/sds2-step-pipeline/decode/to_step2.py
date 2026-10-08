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
from instances import material_instances, subm_vertices
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
                bbox_error = np.abs(np.ptp(P, axis=0) - np.ptp(yz, axis=0)).sum()
                score = (int(np.sum(dist < 0.02)), -round(float(bbox_error), 5))
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


USE_BREP = True       # exact faceted solids from the piece file's own topology (brep.py); False = approximate builders
USE_HOLES = True      # cut the piece's bolt holes / slots (brep.holes) into its exact solid
_BREP = {}
CONCRETE = set()      # (job, piece) whose exact volume matches SDS2's weight at concrete density
HOLES_CUT = collections.Counter()


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
    if not USE_BREP or p["wt"] <= 0:
        return None
    key = (job, sid)
    if key not in _BREP:
        sh = None
        try:
            with open(os.path.join(job, "subm", str(sid)), "rb") as f:
                data = f.read()
            r = brep.parse(data)
            if r is not None:
                sh = brep.solid(*r)
            if sh is not None:
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
            if sh is not None and USE_HOLES:
                H = brep.holes(data)
                HOLES[key] = H
                if H:
                    cut = brep.cut_holes(sh, H)
                    HOLES_CUT["pieces with holes"] += 1
                    HOLES_CUT["holes" if cut is not sh else "holes not cut"] += len(H)
                    sh = cut
        except Exception:
            sh = None
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


def placement(M, o):
    """gp_Trsf for world = o + M.T @ local (inches -> mm), or None if M isn't a rotation."""
    from OCP.gp import gp_Trsf
    R = M.T
    try:
        t = gp_Trsf()
        t.SetValues(*R[0], o[0] * MM, *R[1], o[1] * MM, *R[2], o[2] * MM)
        return t
    except Exception:
        return None


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


def convert(job, out, shared=True):
    """shared=True: exact pieces are written once and placed per instance (STEP assembly); False: one copy each."""
    global SHARED
    SHARED = shared
    pieces = read_pieces(job); shapes = read_shapes(job)
    mems, _ = read_members(job)
    mtype = {m.id: m.type for m in mems}
    mem_by_id = {m.id: m for m in mems}
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    rows = []; skipped_rows = []
    stats = {"plate": 0, "rolled": 0, "skipped": 0, "member_fallback": 0, "exact": 0}
    instance_counts = collections.Counter()
    skipped = collections.Counter()
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    wsum = [0.0, 0.0]; wcache = {}; wdiff = collections.Counter()

    def track(sid, sh, how):
        """Steel weight of the placed solid vs SDS2's piece weight (concrete excluded), one volume per piece build."""
        p = pieces[sid]
        if p["name"].startswith("Conc") or not 0 < p["wt"] < 1e6:          # corrupt weights (Centene: 3e311 lb)
            return
        if re.match(r"GT\d", p["name"]):
            return        # bar grating: SDS2 weighs the open mesh, the solid panel is ~7x that (SampleJob, Centene)
        if (sid, how) not in wcache:
            g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); wcache[(sid, how)] = abs(g.Mass()) / MM ** 3 * 0.2836
        wsum[0] += wcache[(sid, how)]; wsum[1] += p["wt"]
        wdiff[(sid, p["name"], how)] += wcache[(sid, how)] - p["wt"]

    def record_skip(n, sid, inst_no, p, k, origin, reason):
        stats["skipped"] += 1
        skipped[p["name"][:12]] += 1
        skipped_rows.append(dict(member=n, member_type=mtype[n], piece=sid, inst=inst_no,
                                 name=p["name"], kind=k, reason=reason,
                                 ox=round(origin[0], 4), oy=round(origin[1], 4), oz=round(origin[2], 4)))

    parts = {}; root = [None]; hw = []          # hw: placed holes (entry, axis, depth, bolt dia, instance)
    shared_inst = []                            # (part key, local solid, placement, instance label)
    frames = {}                                 # member -> main material placement (bolt record frame)

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

    for n in sorted(mtype):
        if mtype[n] == "Ref Point":
            continue
        main_sid, inst = material_instances(job, n, pieces)
        for sid_, M_, o_ in inst:
            if sid_ == main_sid:
                frames[n] = (M_, o_); break
        if not inst and mtype[n] in T.STRUCTURAL:
            # no fabricated pieces (e.g. joists are vendor-supplied): keep the stage-1 member solid
            m = mem_by_id[n]
            sh = T.solid_for(m, "X", 1)
            if sh is not None:
                lab = st.AddShape(sh, False)
                TDataStd_Name.Set_s(lab, TCollection_ExtendedString(f"{m.type} #{n} / {m.section.name} (member envelope)"))
                stats["member_fallback"] += 1
                if m.type == "JOIST":
                    # Vendor-supplied Greenwood joists have no fabricated pieces. Their job_mtrl
                    # weight is a 2.5/5 lb/ft placeholder, not enough to infer chord/web sizes.
                    # Keep the erection envelope visible, but never call it an exact joist.
                    stats["joist_envelope"] = stats.get("joist_envelope", 0) + 1
                rows.append(dict(member=n, member_type=m.type, piece=0, inst=0, name=m.section.name,
                                 kind="member", builder="joist_envelope_approx" if m.type == "JOIST" else "member_envelope",
                                 ox=round(m.p1[0], 4), oy=round(m.p1[1], 4), oz=round(m.p1[2], 4)))
            continue
        for sid, M, o in inst:
            p = pieces[sid]; k = kind(p)
            instance_counts[(n, sid)] += 1
            inst_no = instance_counts[(n, sid)]
            label = piece_instance_label(mtype[n], n, p["name"], sid, inst_no)
            # exact B-rep: plates / rolled / joists, and bolts (SDS2 stores each nut, head and washer as its own
            # faceted hex / ring piece). Studs and rods keep the true cylinders of special_solid; concrete its prism.
            if (k in ("plate", "rolled") and not TURNED.match(p["name"]) or p["name"].startswith("BLT")) \
                    and not p["name"].startswith("Conc"):
                sh = brep_placed(job, sid, p, M, o)
                if sh is not None:
                    conc = (job, sid) in CONCRETE
                    k2 = "concrete" if conc else "fastener" if p["name"].startswith("BLT") else k
                    sh = add_exact(sid, sh, label)
                    for h in HOLES.get((job, sid), ()) if USE_BOLTS else ():
                        hw.append((o + M.T @ h["c"], -(M.T @ h["axis"]), h["depth"], h["bolt"], len(rows)))
                    stats[k2] = stats.get(k2, 0) + 1; stats["exact"] += 1
                    stats["exact_brep"] = stats.get("exact_brep", 0) + 1
                    if not conc: track(sid, sh, "exact")
                    rows.append(dict(member=n, member_type=mtype[n], piece=sid, inst=inst_no,
                                     name=p["name"], kind=k2, builder="exact_brep",
                                     ox=round(o[0], 4), oy=round(o[1], 4), oz=round(o[2], 4)))
                    continue
            V = subm_vertices(job, sid)
            if (V is None or len(V) < 4) and k in ("plate", "rolled") and not TURNED.match(p["name"]) \
                    and not p["name"].startswith("Conc"):
                V = mesh_vertices(job, sid)        # no tagged outline: use the piece's mesh vertices instead
            if (V is None or len(V) < 4) and k == "rolled" and p["sec"] in shapes and p["L"] > 0:
                # piece file holds no geometry (e.g. 216-B stubs on 7.516 HENRY FORD): nominal straight piece,
                # section over its length, top of section at local y = 0 like the decoded rolled pieces
                s_ = shapes[p["sec"]]
                V = np.array([[x, y, z] for x in (0.0, p["L"]) for y in (0.0, -s_.d) for z in (-s_.bf / 2, s_.bf / 2)])
            if V is None or len(V) < 4 or k == "other" or TURNED.match(p["name"]) or p["name"].startswith("Conc"):
                # weld studs, bolts, anchor rods, concrete: built from their mesh / piece-table dimensions
                sh, k2 = special_solid(job, sid, p, M, o)
                builder = "special_primitive"
                if sh is None and not p["name"].startswith("Conc"):
                    sh, k2 = brep_placed(job, sid, p, M, o), "fastener"      # e.g. threaded studs with no rings
                    if sh is not None:
                        stats["exact"] += 1
                        builder = "exact_brep"
                if sh is None:
                    record_skip(n, sid, inst_no, p, k, o, "no_usable_special_geometry")
                    continue
                sh = add_exact(sid, sh, label)
                stats[k2] = stats.get(k2, 0) + 1; track(sid, sh, k2)
                stats[builder] = stats.get(builder, 0) + 1
                rows.append(dict(member=n, member_type=mtype[n], piece=sid, inst=inst_no,
                                 name=p["name"], kind=k2, builder=builder,
                                 ox=round(o[0], 4), oy=round(o[1], 4), oz=round(o[2], 4)))
                continue
            if k == "plate":
                loc = plate_local(V, p)
            elif k == "rolled" and p["sec"] in shapes:
                loc = rolled_local(V, shapes[p["sec"]], p["L"])
            else:
                loc = None
            if loc is None and k == "rolled" and V is not None and len(V) >= 4 and np.ptp(V[:, 0]) > 0:
                # section record without dimensions (8.007 joists: 30K11 has d = bf = 0): envelope box of the
                # piece's own vertices along local x, like the joist envelopes elsewhere
                lo_, hi_ = V.min(0), V.max(0)
                loc = ([np.array([lo_[0], y, z]) for y, z in ((lo_[1], lo_[2]), (hi_[1], lo_[2]), (hi_[1], hi_[2]), (lo_[1], hi_[2]))],
                       np.array([hi_[0] - lo_[0], 0.0, 0.0]))
            if loc is None:
                record_skip(n, sid, inst_no, p, k, o, "no_usable_piece_geometry")
                continue
            loop, e = loc[0], loc[1]
            holes = loc[2] if len(loc) > 2 else []
            Rt = M.T
            sh = prism([o + Rt @ q for q in loop], Rt @ e, [[o + Rt @ q for q in h] for h in holes])
            if sh is None and k == "plate":
                # refined outline (bent / concave) rejected: fall back to the plain convex-hull plate
                loc2 = plate_local(V)
                if loc2 is not None:
                    sh = prism([o + Rt @ q for q in loc2[0]], Rt @ loc2[1])
            if sh is None and k == "rolled" and sid == main_sid and mem_by_id[n].section is not None:
                # main material stored as a flat 2D outline (zero extent along local x; 7.613 Building_101j W10x26):
                # use the member's own stage-1 solid, oriented from its end points and roll
                sh = T.solid_for(mem_by_id[n], "X", 1)
                if sh is not None:
                    lab = st.AddShape(sh, False)
                    TDataStd_Name.Set_s(lab, TCollection_ExtendedString(label + " member envelope"))
                    stats["member_fallback"] += 1
                    rows.append(dict(member=n, member_type=mtype[n], piece=sid, inst=inst_no,
                                     name=p["name"], kind="member", builder="member_envelope",
                                     ox=round(o[0], 4), oy=round(o[1], 4), oz=round(o[2], 4)))
                    continue
            skip_reason = "fallback_builder_failed"
            if sh is not None and 0 < p["wt"] < 1e6:
                # approximate solid wildly heavier than SDS2's weight (7.708 Center Grove: wall "plate" 7 5/8x384
                # whose vertices coincide -> mesh box of 50 million lb): report instead of writing it
                g_ = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g_); w_ = abs(g_.Mass()) / MM ** 3 * 0.2836
                if w_ > 5 * p["wt"] and w_ - p["wt"] > 1000:
                    sh = None
                    skip_reason = "fallback_over_5x_source_weight"
            if sh is None:
                record_skip(n, sid, inst_no, p, k, o, skip_reason)
                continue
            lab = st.AddShape(sh, False)
            TDataStd_Name.Set_s(lab, TCollection_ExtendedString(label))
            stats[k] += 1; track(sid, sh, "approx")
            builder = "profile_fallback" if k == "rolled" else "plate_fallback"
            stats[builder] = stats.get(builder, 0) + 1
            rows.append(dict(member=n, member_type=mtype[n], piece=sid, inst=inst_no,
                             name=p["name"], kind=k, builder=builder,
                             ox=round(o[0], 4), oy=round(o[1], 4), oz=round(o[2], 4)))
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
            if SHARED:
                add_exact(("bolt",) + key, ("shared", bparts[key], t), lab)
            else:
                from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
                add_exact(None, BRepBuilderAPI_Transform(bparts[key], t, True).Shape(), lab)
            stats["bolts"] = stats.get("bolts", 0) + 1
            stats["bolts_" + src] = stats.get("bolts_" + src, 0) + 1
    if shared_inst:
        # a few parts read back invalid once placed through an assembly location although the same solid is valid as a
        # placed copy (SCHUCKERS C12x20.7, PIPE 1 1/2: 6 of 288 parts); test each part once at its first placement
        # and write the instances of failing parts as placed copies
        first = {}
        for key, local, trsf, _ in shared_inst: first.setdefault(key, (local, trsf))
        bad = assembly_check(first)
        from OCP.TopLoc import TopLoc_Location
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        root[0] = st.NewShape()
        TDataStd_Name.Set_s(root[0], TCollection_ExtendedString(os.path.basename(job.rstrip("\\/"))))
        for key, local, trsf, label in shared_inst:
            if key in bad:
                lab = st.AddShape(BRepBuilderAPI_Transform(local, trsf, True).Shape(), False)
                TDataStd_Name.Set_s(lab, TCollection_ExtendedString(label)); continue
            if key not in parts:
                parts[key] = st.AddShape(local, False)
                pn = f"{pieces[key]['name']} (piece {key})" if key in pieces else label
                TDataStd_Name.Set_s(parts[key], TCollection_ExtendedString(pn))
            comp = st.AddComponent(root[0], parts[key], TopLoc_Location(trsf))
            TDataStd_Name.Set_s(comp, TCollection_ExtendedString(label))
        stats["parts_written_flat"] = len(bad)
    if root[0] is not None:
        st.UpdateAssemblies()
        stats["unique_parts"] = len(parts)
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    w = STEPCAFControl_Writer(); w.SetNameMode(True)
    w.Transfer(doc, STEPControl_AsIs)
    ok = w.Write(out) == IFSelect_RetDone
    with open(os.path.splitext(out)[0] + "_pieces.csv", "w", newline="") as f:
        cw = csv.DictWriter(f, fieldnames=("member", "member_type", "piece", "inst", "name", "kind",
                                           "builder", "ox", "oy", "oz"))
        cw.writeheader(); cw.writerows(rows)
    with open(os.path.splitext(out)[0] + "_skipped.csv", "w", newline="") as f:
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
    return ok, stats


if __name__ == "__main__":
    main()
