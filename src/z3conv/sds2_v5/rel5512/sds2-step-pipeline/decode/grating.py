"""Bar grating and grating treads (G[TR]... pieces) built from SDS2's own piece data (patch sds2-grating-cylinders).

What SDS2 stores (piece files of 7.2xx-8.0xx jobs; checked on SLC4 DATABANK 7.331, SHERIFFS OFFICE 7.425, One Light
Tower 7.312, PSU BNR 8.004):
  - the bearing bars and end bands as faces. On panels (GR) they sew into one closed solid; on treads (GT) the bars and
    the nosing are open tubes whose two end outlines lie on the carrier plates / bands (those edges have 3 users), so
    the piece "does not sew" and v4 / v5 wrote the grating as a solid panel (5-10x SDS2's weight)
  - every cross bar as one flat rectangle on the walking face (0.001 in below or 0.005 in above it), exactly as wide as
    the cross bar (a zero-thickness marker, not a solid)
  - the piece-table slot holds the grating fields as 8 numbers: bearing bar thickness, bar depth, bar spacing, cross bar
    width, cross bar depth, cross bar spacing, panel width, panel length (f64 at +0x168 in 852 / 902-B slots, +0x158 in
    8.0 slots; located by value, see slot_fields)
build() reproduces that grating: closed bodies as stored; open bar / nosing tubes closed at their own stored end
outlines only where each outline lies on a stored face of the band / carrier it is welded to (a contact face that
disappears in the union), otherwise the closed cells bounded by the stored faces (OCC MakerVolume, non-manifold treads);
cross bars = their stored rectangles extruded into the grating by the slot's cross bar depth; all fused into one solid.
SDS2's piece weight is the weight of exactly this union (SLC4 GR1 3/4x23 15/16 x 97 1/2: 199.0 lb built vs 199.0 lb
SDS2; SHERIFFS GR3/4x23 9/16: 22.03 vs 22.06 lb), so a result is accepted within WEIGHT_TOL of SDS2's weight, or when
lighter, inside the record's W x L stock and of the stock's weight per plan area (a panel cut down in SDS2 keeps the
uncut panel's weight: TEMP Wayne Farms GR1 1/4x36 cut to 11 1/2 in: 0.322 = 11.5 / 36); otherwise the caller keeps the
tagged panel. Nothing is added that the piece does not store: no bar positions are guessed and no open mesh is closed
with new boundary faces.
"""
import collections, struct
import numpy as np
import brep

MM = 25.4
WEIGHT_TOL = 0.03          # |built / SDS2 weight - 1| allowed for an exact grating
MAX_CELL_FACES = 300       # larger non-manifold pieces are not partitioned into cells (FMI 7.132 GR1 1/2x101: 567
                           # faces, 2-5 min, and the cells closed voids: 3.8x SDS2's weight)
STEEL = 0.2836             # lb / in3
CUT_DENSITY = (0.93, 1.25)  # cut panel: (built / SDS2 weight) / (plan / stock area) allowed; < 1: steel missing, > 1:
                            # bands along the cut edges (data-3, 115 cut pieces: 0.94-1.20, narrow 4 in strips 1.20)


def _edge_use(faces):
    E = collections.Counter()
    for f in faces:
        for l in brep.loops_of(f):
            for a, b in zip(l, l[1:] + l[:1]):
                if a != b:
                    E[(min(a, b), max(a, b))] += 1
    return E


def _chain(edges):
    """Undirected edges -> closed vertex loops, or None unless every vertex has exactly two of them."""
    adj = collections.defaultdict(list)
    for a, b in edges:
        adj[a].append(b); adj[b].append(a)
    if not adj or any(len(v) != 2 for v in adj.values()):
        return None
    loops, seen = [], set()
    for s in adj:
        if s in seen:
            continue
        loop, prev, cur = [s], s, adj[s][0]
        seen.add(s)
        while cur != s:
            if cur in seen:
                return None
            loop.append(cur); seen.add(cur)
            a, b = adj[cur]
            prev, cur = cur, (b if a == prev else a)
        loops.append(loop)
    return loops


def _normal(P):
    c = P.mean(0)
    n = sum(np.cross(P[k] - c, P[(k + 1) % len(P)] - c) for k in range(len(P)))
    L = np.linalg.norm(n)
    return c, (n / L if L > 1e-12 else None)


def _on_stored_face(V, loop, others):
    """True if the loop lies in the plane of one of the other bodies' stored faces and inside its outline: the end face
    it would close is a contact face of the union (internal), not new boundary."""
    from shapely.geometry import Polygon, Point
    P = V[loop]
    for f in others:
        ls = brep.loops_of(f)
        if not ls or len(ls[0]) < 3:
            continue
        Q = V[ls[0]]
        c, n = _normal(Q)
        if n is None or np.abs((P - c) @ n).max() > 1e-3:
            continue
        u = np.cross(n, [1.0, 0, 0] if abs(n[0]) < 0.9 else [0, 1.0, 0]); u /= np.linalg.norm(u); w = np.cross(n, u)
        try:
            # v5.5.8: the covering face with its own holes (inner loops): a tube end over a hole in a carrier plate
            # is not a contact face, and closing it would add a face the source does not store
            holes = [[(q @ u, q @ w) for q in V[l]] for l in ls[1:] if len(l) >= 3]
            poly = Polygon([(q @ u, q @ w) for q in Q], holes).buffer(1e-3)
            end = Polygon([(q @ u, q @ w) for q in P])
        except Exception:
            continue
        if not end.is_valid or end.area <= 0:
            if all(poly.covers(Point(p @ u, p @ w)) for p in P):
                return True
            continue
        if poly.covers(end):
            return True
    return False


def _closed_faces(V, faces, others=()):
    """Faces of an open body plus one planar end face per loop of its free edges (bar / nosing tubes whose ends sit on
    a band or carrier plate), or None if the free edges are not planar closed loops or an end outline does not lie on a
    stored face of another body (that would be closing an open mesh, which is not done)."""
    E = _edge_use(faces)
    if any(c > 2 for c in E.values()):
        return None
    free = [e for e, c in E.items() if c == 1]
    if not free:
        return list(faces)
    loops = _chain(free)
    if not loops:
        return None
    for l in loops:
        if len(l) < 3:
            return None
        c, n = _normal(V[l])
        if n is None or np.abs((V[l] - c) @ n).max() > 1e-4:
            return None
        if not _on_stored_face(V, l, others):
            return None
    return list(faces) + loops


def _prism(P, vec):
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    poly = BRepBuilderAPI_MakePolygon()
    for q in P:
        poly.Add(gp_Pnt(*(q * MM)))
    poly.Close()
    f = BRepBuilderAPI_MakeFace(poly.Wire(), True)
    if not f.IsDone():
        return None
    return BRepPrimAPI_MakePrism(f.Face(), gp_Vec(*(vec * MM))).Shape()


def slot_fields(slot, depth, cross_w=None):
    """The 8 grating numbers in a piece-table slot, located by value: [bar thickness, bar depth, bar spacing, cross bar
    width, cross bar depth, cross bar spacing, width, length] as consecutive f64 (7.2+ records) or f32 (7.0 / 7.1),
    whose depth equals the bars' depth in the B-rep and whose cross bar width equals the stored cross bar rectangles."""
    for code, size in (("d", 8), ("f", 4)):
        n = 8 * size
        for o in range(0, len(slot) - n + 1, 2):
            v = struct.unpack(">8" + code, slot[o:o + n])
            if not all(np.isfinite(v)):
                continue
            bt, d, sp, cw, cd, cs, W, L = v
            tol = 2e-3 if size == 8 else 5e-3
            if abs(d - depth) > tol or not (0 < bt <= 1.0 and bt < sp <= 12 and 0 < cw <= 1.0 and 0 < cd <= 12
                                            and 0 < cs <= 48 and 0 < W < 2000 and 0 < L < 5000):
                continue
            if cross_w is not None and abs(cw - cross_w) > tol:
                continue
            # cross bars recorded deeper than the bearing bars (1504 EQUADOR GR3/16: 0.5 in under a 0.197 in plank;
            # DSCC mesh panels) are built as recorded, protruding below the bars: SDS2's weight confirms it (1.012), and
            # such a piece must match SDS2's weight (no cut-panel exemption, see build)
            return dict(offset=o, fmt=code, bar_t=bt, depth=d, bar_spacing=sp, cross_w=cw, cross_d=cd,
                        cross_deeper_than_bars=cd > d + tol, cross_spacing=cs, width=W, length=L)
    return None


def _plan_ratio(V, faces, n, fields):
    """Plan area of the piece / the record's W x L (validation only, nothing is built from it): the union of the stored
    faces that face the walking-face normal (bar / band / nosing tops, cross bar rectangles), projected on the walking
    face, with the open spaces between bars closed by half the larger bar / cross bar spacing. A panel cut from its
    stock keeps the stock's weight per plan area, so built / SDS2 weight ~ this ratio (data-3: 0.94-1.20x it over 115
    cut pieces; narrow strips carry relatively more band). None if it cannot be computed."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    try:
        u = np.cross(n, [1.0, 0, 0] if abs(n[0]) < 0.9 else [0, 1.0, 0]); u /= np.linalg.norm(u); w = np.cross(n, u)
        polys = []
        for f in faces:
            ls = brep.loops_of(f)
            if not ls or len(ls[0]) < 3:
                continue
            _, nn = _normal(V[ls[0]])
            if nn is None or abs(nn @ n) < 0.9:
                continue
            pg = Polygon([(q @ u, q @ w) for q in V[ls[0]]]).buffer(0)
            if pg.area > 0:
                polys.append(pg)
        r = max(fields["bar_spacing"], fields["cross_spacing"]) / 2 + 0.02
        a = unary_union(polys).buffer(r, 4).buffer(-r, 4).area
        wl = fields["width"] * fields["length"]
        return a / wl if a > 0 and wl > 0 else None
    except Exception:
        return None


def _volume(sh):
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g)
    return abs(g.Mass()) / MM ** 3


def _occ_faces(V, faces):
    """Planar OCC faces (outer loop + inner loops) of stored piece faces, in mm; None if one cannot be made."""
    from OCP.gp import gp_Pnt
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
    from OCP.ShapeFix import ShapeFix_Face

    def wire(idx):
        poly = BRepBuilderAPI_MakePolygon()
        for i in idx:
            poly.Add(gp_Pnt(*(V[i] * MM)))
        poly.Close()
        return poly.Wire() if poly.IsDone() else None
    out = []
    for f in faces:
        ls = brep.loops_of(f)
        if not ls:
            continue
        ls.sort(key=lambda l: -brep._area(V[l]))
        w0 = wire(ls[0])
        if w0 is None:
            return None
        mf = BRepBuilderAPI_MakeFace(w0, True)
        if not mf.IsDone():
            return None
        for l in ls[1:]:
            w = wire(l)
            if w is not None:
                mf.Add(w)
        face = mf.Face()
        if len(ls) > 1:
            fx = ShapeFix_Face(face); fx.FixOrientation(); fx.Perform(); face = fx.Face()
        out.append(face)
    return out


def _cells(V, faces):
    """Closed cells bounded by the stored faces (OCC BOPAlgo_MakerVolume): tread bars and nosing are open tubes that
    end on the carrier plates and overlap the next face, so they are closed by the carrier faces SDS2 stores, not by
    new faces. Returns the list of cell solids or None."""
    from OCP.BOPAlgo import BOPAlgo_MakerVolume
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID
    try:
        from OCP.TopTools import TopTools_ListOfShape
    except ImportError:
        from OCP.collections import List_TopoDS_Shape as TopTools_ListOfShape
    fl = _occ_faces(V, faces)
    if not fl:
        return None
    args = TopTools_ListOfShape()
    for f in fl:
        args.Append(f)
    mv = BOPAlgo_MakerVolume(); mv.SetArguments(args); mv.SetRunParallel(False); mv.SetIntersect(True)
    mv.SetAvoidInternalShapes(True)
    mv.Perform()
    if mv.HasErrors():
        return None
    out = []
    ex = TopExp_Explorer(mv.Shape(), TopAbs_SOLID)
    while ex.More():
        out.append(ex.Current()); ex.Next()
    return out or None


def build(V, F, wt, slot):
    """-> (local solid, info) or (None, info with 'why'). V, F: brep.parse() of the piece file; wt: SDS2 piece weight
    (lb); slot: the piece's raw piece-table record."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID
    try:
        from OCP.TopTools import TopTools_ListOfShape
    except ImportError:
        from OCP.collections import List_TopoDS_Shape as TopTools_ListOfShape
    info = dict(bodies=0, closed_as_stored=0, closed_at_stored_ends=0, cells=0, cross_bars=0)
    F = brep.conform(V, F)                       # merge coincident vertices, split T-junctions (as brep.solid does)
    solids, markers, body_faces, stuck = [], [], [], False
    parts = brep.bodies(F)
    for bi, P in enumerate(parts):
        if len(P) == 1 and len(brep.loops_of(P[0])) == 1:
            markers.append(brep.loops_of(P[0])[0]); continue     # a lone flat face: a cross bar rectangle
        info["bodies"] += 1
        body_faces.append(P)
        sh = brep._solid(V, P)
        if sh is not None:
            info["closed_as_stored"] += 1
        else:
            others = [f for bj, Q in enumerate(parts) if bj != bi and len(Q) > 1 for f in Q]
            P2 = _closed_faces(V, P, others)
            sh = brep._solid(V, P2) if P2 is not None else None
            if sh is None:
                stuck = True; continue
            info["closed_at_stored_ends"] += 1
        solids.append(sh)
    if not body_faces:
        info["why"] = "no bar / band bodies in the piece faces"
        return None, info
    if stuck:
        # non-manifold treads (bars / nosing overlapping the carrier faces): closed cells of all stored faces
        nfaces = sum(len(P) for P in body_faces)
        if nfaces > MAX_CELL_FACES:
            info["why"] = f"bars / bands do not close and the piece is too large to partition ({nfaces} faces)"
            return None, info
        solids = _cells(V, [f for P in body_faces for f in P])
        if not solids:
            info["why"] = "bar / band faces do not bound closed cells"
            return None, info
        info["cells"] = len(solids)
    body_v = [V[sorted({i for f in P for i in f})] for P in body_faces]
    allv = np.vstack(body_v)
    n = None
    if markers:
        ref, normals = None, []
        for l in markers:
            _, nn = _normal(V[l])
            if nn is None:
                info["why"] = "degenerate cross bar rectangle"; return None, info
            ref = nn if ref is None else ref
            normals.append(nn if nn @ ref >= 0 else -nn)
        n = normals[0]
        if any(abs(m @ n) < 0.9999 for m in normals):
            info["why"] = "cross bar rectangles not parallel"; return None, info
        widths = []
        for l in markers:
            q = V[l] - np.outer(V[l] @ n, n)
            q = q - q.mean(0)
            widths.append(float(np.ptp(q @ np.linalg.svd(q, full_matrices=False)[2][1])))
        cross_w = float(np.median(widths))
    else:
        ext = np.ptp(allv, 0); n = np.eye(3)[int(np.argmin(ext))]; cross_w = None
    # the bars' depth is the slot's depth field; a tread's own extent also spans its deeper carrier plates, so every
    # body extent along the walking-face normal is a candidate
    fields = None
    for depth in sorted({round(float(np.ptp(B @ n)), 4) for B in body_v}, reverse=True):
        fields = slot_fields(slot, depth, cross_w)
        if fields:
            break
    if fields:
        info["slot"] = {k: (round(v, 5) if isinstance(v, float) else v) for k, v in fields.items()}
    tools = []
    if markers:
        if not fields:
            info["why"] = "cross bar depth not found in the piece record"; return None, info
        cd = fields["cross_d"]
        s_all = allv @ n
        smin, smax = float(s_all.min()), float(s_all.max())
        for l in markers:
            P = V[l]
            sm = float(np.mean(P @ n))
            top, dirv = (smax, -n) if abs(sm - smax) <= abs(sm - smin) else (smin, n)
            if abs(sm - top) > 0.02:
                info["why"] = "cross bar rectangle not on the walking face"; return None, info
            t = _prism(P + np.outer(top - P @ n, n), dirv * cd)    # stored rectangle on the walking face, down cd
            if t is None:
                info["why"] = "cross bar prism failed"; return None, info
            tools.append(t)
        info["cross_bars"] = len(tools)
    if len(solids) == 1 and not tools:
        res = solids[0]
    else:
        args = TopTools_ListOfShape(); args.Append(solids[0])
        tl = TopTools_ListOfShape()
        for s in solids[1:] + tools:
            tl.Append(s)
        op = BRepAlgoAPI_Fuse(); op.SetArguments(args); op.SetTools(tl); op.SetRunParallel(False)
        op.SetFuzzyValue(1e-4)
        op.Build()
        if not op.IsDone():
            info["why"] = "boolean fuse failed"; return None, info
        # no ShapeUpgrade_UnifySameDomain: it merges the walking surface into one face with a hole per opening
        # (OLT GT1/8x34 5/8: 392 inner wires) and BRepCheck of such a face is quadratic in its wires: 3.0 s instead
        # of 0.9 s per placed grating in the --verify read-back (SLC4 GR1 3/4x35 13/16: 4.8 s vs 1.7 s)
        res = op.Shape()
    if not BRepCheck_Analyzer(res).IsValid():
        info["why"] = "fused grating is not a valid solid"; return None, info
    ex = TopExp_Explorer(res, TopAbs_SOLID); ns = 0
    while ex.More():
        ns += 1; ex.Next()
    info["solids"] = ns
    built = _volume(res) * STEEL
    info["built_lb"] = round(built, 3)
    info["sds2_lb"] = round(wt, 3)
    r = built / wt if wt > 0 else None
    info["weight_ratio"] = None if r is None else round(r, 4)
    if r is not None and abs(r - 1) <= WEIGHT_TOL:
        return res, info
    # a panel cut down from its stock (strips, notches, openings): SDS2 weighs the uncut W x L panel (TEMP Wayne
    # Farms GR1 1/4x36 cut to 11 1/2 in wide: 0.322 = 11.5 / 36), so a lighter result is accepted when the piece's
    # own geometry lies within the W x L stock of its record, its cross bars are stored, and its weight per plan area
    # is the stock's (built / SDS2 weight = CUT_DENSITY x plan / stock area): a piece that lost bars or closed voids
    # fails this
    why = ""
    if r is not None and r < 1 and fields and not fields.get("cross_deeper_than_bars"):
        plan = sorted(np.ptp(allv - np.outer(allv @ n, n), 0))[-2:]
        stock = sorted((fields["width"], fields["length"]))
        pr = _plan_ratio(V, [f for P in body_faces for f in P] + markers, n, fields)
        info["plan_ratio"] = None if pr is None else round(pr, 4)
        if not (plan[0] <= stock[0] + 0.05 and plan[1] <= stock[1] + 0.05):
            why = "larger than its W x L stock"
        elif not markers:
            why = "no cross bars stored although the record has them"
        elif pr is None or not CUT_DENSITY[0] <= r / pr <= CUT_DENSITY[1]:
            why = (f"weight per plan area {r / pr:.2f}x the stock's" if pr else "plan area not measurable")
        else:
            info["cut_from_stock"] = True
            return res, info
    info["why"] = (f"built grating {r:.3f}x SDS2's weight (outside 1 +- {WEIGHT_TOL}, not a cut of its W x L stock"
                   f"{': ' + why if why else ''})" if r is not None else "no SDS2 weight to validate the built grating")
    return None, info
