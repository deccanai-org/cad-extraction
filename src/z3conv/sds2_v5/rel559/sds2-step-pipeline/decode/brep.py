"""Exact piece solids from the piece file's own boundary representation (subm/<id>).

Layout (7.1xx-8.0xx, big-endian): u32 nv, nf, ne at 0x1C/0x20/0x24, 4 pad bytes; nv vertex records of 28 bytes
(3 x f64, then u8 tag + u24 id) from 0x2C; ne loop entries of 10 bytes (u32 vertex index + 6 flag bytes); then nf face
records of 22 bytes: u16 0, u16 = number of loop entries the face uses (in order), kind byte (7 = work-line / mid-plane
marker face). A face's entries can hold several loops, each closed by repeating its first vertex (hollow-section end
faces). 7.0xx: counts at 0x06, 24-byte vertices, 8-byte loop entries, 16-byte face records (count at +0, markers have
kind & 0xE0 == 0xE0); some 7.1xx jobs use the 7.0 records with the counts at 0x0E. Faces are sewn into a closed shell -> solid; callers fall back to the approximate builders.
"""
import struct
import numpy as np

MM = 25.4
# (count header offset, vertex record, loop entry, face record, count offset in the face record, marker-face test on
# the kind byte that follows the count)
LAYOUTS = [(0x1C, 28, 10, 22, 2, lambda k: k == 7),              # 7.1xx-8.0xx
           (0x06, 24, 8, 16, 0, lambda k: k & 0xE0 == 0xE0),      # 7.0xx: vertices without the tag word
           (0x0E, 24, 8, 16, 0, lambda k: k & 0xE0 == 0xE0)]      # early 7.1xx (SCHIEL, HARRISON 7.135): 7.0 records


def parse(b, hdr=None, vrec=None, lrec=None, frec=None, co=None, marker=None):
    """-> (V, faces as lists of vertex indices) or None. With no layout given, tries the known ones."""
    if hdr is None:
        for Lo in LAYOUTS:
            r = parse(b, *Lo)
            if r is not None:
                return r
        return None
    if len(b) < hdr + 12:
        return None
    nv, nf, ne = struct.unpack(">3I", b[hdr:hdr + 12])
    if not (3 < nv < 200000 and 0 < nf < 100000 and nf <= ne < 1000000):
        return None
    v0 = hdr + 16                                  # 4 pad bytes, then records of 3 x f64 (+ u8 tag + u24 id on 7.1+)
    if v0 + vrec * nv + lrec * ne > len(b):
        return None
    V = np.array([struct.unpack(">3d", b[v0 + vrec * i:v0 + vrec * i + 24]) for i in range(nv)])
    if not np.isfinite(V).all() or np.abs(V).max() > 1e5:
        return None
    l0 = v0 + vrec * nv
    loops = [struct.unpack(">I", b[l0 + lrec * k:l0 + lrec * k + 4])[0] for k in range(ne)]
    if max(loops) >= nv:
        return None
    # face records: u16 loop-entry count (consumed in order; the counts must sum to ne), then the kind byte that marks
    # work-line / mid-plane marker faces
    f0 = l0 + lrec * ne
    if f0 + frec * nf > len(b):
        return None
    counts = [struct.unpack(">H", b[f0 + frec * k + co:f0 + frec * k + co + 2])[0] for k in range(nf)]
    if not all(1 <= c <= ne for c in counts) or sum(counts) != ne:
        return None
    kinds = [b[f0 + frec * k + co + 2] for k in range(nf)]
    faces, k = [], 0
    for c, kd in zip(counts, kinds):
        if c >= 3 and not marker(kd):
            faces.append(loops[k:k + c])
        k += c
    return V, faces


def holes(b):
    """Bolt holes of a 7.1xx-8.0xx piece file -> list of dicts (piece-local inches) or [] when the tail doesn't match.
    Header u32 nh, ng, nx at 0x00; after the face records: nh hole records of 46 B (centre 3 x f64, depth f64 = material
    thickness, flag u8, group u8, hole type u8, ...), ng group records of 146 B (3x3 orientation, row 3 = hole axis;
    origin 3 x f64; hole diameter, bolt diameter, slot length, slot angle f64), nx 172-B blocks (not holes).
    Each hole runs from its centre along -axis for its depth."""
    if len(b) < 0x2C:
        return []
    old = _holes_40(b)
    if old is not None:
        return old
    nh, ng, nx = struct.unpack(">3I", b[0:12])
    nv, nf, ne = struct.unpack(">3I", b[0x1C:0x28])
    if nh == 0 or ng == 0 or nh > 10000 or ng > 1000:
        return []
    t0 = 0x2C + 28 * nv + 10 * ne + 22 * nf
    if len(b) - t0 - (46 * nh + 146 * ng + 172 * nx) not in (0, 45):     # some 8.007 builds add a 45-byte trailer
        return []
    G = []
    g0 = t0 + 46 * nh
    for j in range(ng):
        d = struct.unpack(">16d", b[g0 + 146 * j:g0 + 146 * j + 128])
        G.append((np.array(d[:9]).reshape(3, 3), d[12], d[13], d[14], d[15]))
    out = []
    for i in range(nh):
        r = b[t0 + 46 * i:t0 + 46 * i + 46]
        c = np.array(struct.unpack(">3d", r[:24])); depth = struct.unpack(">d", r[24:32])[0]
        R, dia, bolt, slot, ang = G[min(r[33], ng - 1)]
        if not (0 < dia < 12 and 0 < depth < 24):
            continue
        out.append(dict(c=c, axis=R[2], depth=depth, dia=dia, bolt=bolt, slot=slot, ang=ang, R=R, type=r[34]))
    return out


def _holes_40(b):
    """7.0xx and early 7.1xx piece files (7.0 records, counts at 0x06 or 0x0E): u16 nh, ng at 0x00; after the face
    records nh hole records of 40 B (centre 3 x f64, depth f32, group index = high nibble of byte +29) and ng group
    records of 128 B (3x3 orientation f64, row 3 = hole axis; hole diameter, bolt diameter, slot length, slot angle
    as f32 at +96/+100/+104/+108). Mapped field by field against the Merriam 7.135 twin whose other copy has the
    7.1+ records (1,300 / 1,300 holes, 408 / 408 groups identical). None if the file isn't in this layout."""
    nh, ng = struct.unpack(">2H", b[0:4])
    if nh == 0 or ng == 0:
        return None
    for h in (0x06, 0x0E):
        if len(b) < h + 12:
            continue
        nv, nf, ne = struct.unpack(">3I", b[h:h + 12])
        if not (3 < nv < 200000 and 0 < nf < 100000 and nf <= ne < 1000000):
            continue
        t0 = h + 16 + 24 * nv + 8 * ne + 16 * nf
        if len(b) - t0 != 40 * nh + 128 * ng:
            continue
        G = []
        for j in range(ng):
            g = b[t0 + 40 * nh + 128 * j:t0 + 40 * nh + 128 * (j + 1)]
            R = np.array(struct.unpack(">9d", g[:72])).reshape(3, 3)
            G.append((R,) + struct.unpack(">4f", g[96:112]))
        out = []
        for i in range(nh):
            r = b[t0 + 40 * i:t0 + 40 * i + 40]
            c = np.array(struct.unpack(">3d", r[:24])); depth = struct.unpack(">f", r[24:28])[0]
            R, dia, bolt, slot, ang = G[min(r[29] >> 4, ng - 1)]
            if not (0 < dia < 12 and 0 < depth < 24):
                continue
            out.append(dict(c=c, axis=R[2], depth=depth, dia=dia, bolt=bolt, slot=slot, ang=ang, R=R, type=r[29] & 0xF))
        return out
    return None


def cut_holes(sh, H):
    """Subtract the holes (round or slotted, piece-local) from a local solid; returns the uncut solid if the boolean fails."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    try:
        from OCP.TopTools import TopTools_ListOfShape
    except ImportError:                                   # OCP 8.x: NCollection lists live in OCP.collections
        from OCP.collections import List_TopoDS_Shape as TopTools_ListOfShape
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.GC import GC_MakeArcOfCircle, GC_MakeSegment
    from OCP.gp import gp_Pnt, gp_Ax2, gp_Dir, gp_Vec
    if not H:
        return sh
    tools = TopTools_ListOfShape()
    for h in H:
        a = -np.asarray(h["axis"], float); a /= np.linalg.norm(a)
        p0 = (h["c"] - a * 0.05) * MM                     # start just outside the entry face
        L = (h["depth"] + 0.1) * MM; r = h["dia"] / 2 * MM
        try:
            if h["slot"] <= 0:
                tools.Append(BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*p0), gp_Dir(*a)), r, L).Shape())
                continue
            d = np.cos(h["ang"]) * h["R"][0] + np.sin(h["ang"]) * h["R"][1]
            d = d - a * (d @ a); d /= np.linalg.norm(d); n = np.cross(a, d)
            s = h["slot"] / 2 * MM
            P = lambda u, v: gp_Pnt(*(p0 + d * u + n * v))
            e = [GC_MakeSegment(P(-s, -r), P(s, -r)).Value(), GC_MakeArcOfCircle(P(s, -r), P(s + r, 0), P(s, r)).Value(),
                 GC_MakeSegment(P(s, r), P(-s, r)).Value(), GC_MakeArcOfCircle(P(-s, r), P(-s - r, 0), P(-s, -r)).Value()]
            w = BRepBuilderAPI_MakeWire()
            for c in e: w.Add(BRepBuilderAPI_MakeEdge(c).Edge())
            tools.Append(BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(w.Wire()).Face(), gp_Vec(*(a * L))).Shape())
        except Exception:
            continue
    if tools.Size() == 0:
        return sh
    try:
        args = TopTools_ListOfShape(); args.Append(sh)
        op = BRepAlgoAPI_Cut(); op.SetArguments(args); op.SetTools(tools); op.SetRunParallel(False); op.Build()
        if not op.IsDone():
            return sh
        res = op.Shape()
        if not BRepCheck_Analyzer(res).IsValid():
            return sh
        # the boolean returns a compound; a single-solid result is returned as the solid itself
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_SOLID, TopAbs_COMPOUND
        from OCP.TopoDS import TopoDS
        if res.ShapeType() == TopAbs_COMPOUND:
            ex = TopExp_Explorer(res, TopAbs_SOLID); sols = []
            while ex.More(): sols.append(ex.Current()); ex.Next()
            if len(sols) == 1:
                return TopoDS.Solid(sols[0])
        return res
    except Exception:
        return sh


_CLEAN_LOOPS = False  # set only inside _repaired(): loops_of() then also splits keyholes and drops spikes


def loops_of(f):
    """A face's entries are one or more loops back to back, each closed by repeating its first vertex
    (hollow-section end faces: outer loop, then inner). A face with no repeat is a single loop.
    In the repair stage (_CLEAN_LOOPS) bridges are read as such:
      - a return to the loop's first vertex that comes straight back along the loop's first edge (a -> b ... b -> a) is a
        keyhole bridge, not the end of the loop. 7.6xx HSS end faces are stored as [4, 1, 0, 5, 6, 1, 4, 7, 8, 9]:
        outer corner 4, bridge to inner corner 1, inner ring 1-0-5-6, bridge back to 4, outer ring 4-7-8-9. Read with
        the plain rule that was a non-simple loop [4, 1, 0, 5, 6, 1] plus a triangle [7, 8, 9]; 3-6 edges stayed free and
        the HSS fell back to an extruded profile (data-3 10 World Trade 7.619: 549 HSS placements);
      - inside a loop, edges stored once in each direction (keyhole bridges, zero-width spikes a -> b -> a) cancel and
        the remaining edges are chained into the loops they bound (outer ring, inner ring). Built as one polygon the
        bridge edges stayed unmatched (METHODIST 7.132 HSS / pipe end faces).
    Not applied in the first passes: after conform() merges coincident vertices some stored faces carry an
    out-and-back edge that their neighbours need (DSCC 7.312 W10x12, SOCORRO 7.425 HSS5x2x5/16 build only with it)."""
    out, cur = [], []
    for i in f:
        if cur and i == cur[0] and len(cur) >= 3 and not (_CLEAN_LOOPS and cur[-1] == cur[1]):
            out.append(cur); cur = []
        elif not cur or i != cur[-1]:
            cur.append(i)
    if len(cur) >= 3: out.append(cur)
    if not _CLEAN_LOOPS:
        return out
    return [l for l in _cancel_bridges(out) if len(l) >= 3]


def _cancel_bridges(ls):
    """A face's stored loops -> the loops they bound: edges present once in each direction (keyhole bridges
    a -> b ... b -> a, zero-width spikes a -> b -> a, and an inner loop running along the outer loop: 7.6xx HSS end
    faces whose top wall is cut away are stored as the outer ring plus an inner ring sharing the top edge, which after
    the T-junction split of conform() is a pair of opposite edges - data-3 Kerman 7.619 HSS5x3) cancel; the remaining
    edges are chained in stored order. Loops without such a pair, or whose remaining edges do not chain into closed
    loops, are returned as stored."""
    import collections
    E = [(l[k], l[(k + 1) % len(l)]) for l in ls for k in range(len(l)) if l[k] != l[(k + 1) % len(l)]]
    cnt = collections.Counter(E)
    if not any(cnt[(b, a)] for a, b in cnt):
        return ls
    keep = {e: c - min(c, cnt[(e[1], e[0])]) for e, c in cnt.items()}
    seq = []
    for e in E:
        if keep[e] > 0:
            seq.append(e); keep[e] -= 1
    if not seq:
        return []
    nxt_of = collections.defaultdict(list)
    for x, (a, _) in enumerate(seq):
        nxt_of[a].append(x)
    used = [False] * len(seq); loops = []
    for s0 in range(len(seq)):
        if used[s0]:
            continue
        lp, e = [], s0
        while True:
            used[e] = True; a, b = seq[e]; lp.append(a)
            if b == seq[s0][0]:
                break
            cand = [x for x in nxt_of[b] if not used[x]]
            if not cand:
                return ls
            e = min(cand, key=lambda x: (x - e) % len(seq))      # the edge that follows in stored order
        loops.append(lp)
    return loops


def _area(P):
    c = P.mean(0); return np.linalg.norm(sum(np.cross(P[k] - c, P[(k + 1) % len(P)] - c) for k in range(len(P)))) / 2


def bodies(faces):
    """Split faces into separate closed bodies: faces are joined across edges used by exactly two faces; an edge
    shared by more (joist seat angles touching the top chord along a line) separates bodies."""
    import collections
    E = collections.defaultdict(list)
    for k, f in enumerate(faces):
        for l in loops_of(f):
            for a, b in zip(l, l[1:] + l[:1]):
                E[(min(a, b), max(a, b))].append(k)
    par = list(range(len(faces)))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]; a = par[a]
        return a
    for ks in E.values():
        if len(ks) == 2:
            par[find(ks[0])] = find(ks[1])
    G = collections.defaultdict(list)
    for k in range(len(faces)):
        G[find(k)].append(faces[k])
    return list(G.values())


def conform(V, faces, tol=1e-4):
    """Repair pass for meshes that don't close as stored: merge coincident vertices, then split every loop edge at
    the vertices lying on it (T-junctions at cope / clip corners: 7.0-record W beams on SCHIEL and Saralee left
    6-10 free edges each). Returns new faces over the same V indices."""
    key = {}
    rep = np.arange(len(V))
    for i, p in enumerate(np.round(V / tol).astype(np.int64)):
        rep[i] = key.setdefault(tuple(p), i)
    faces = [[int(rep[i]) for i in f] for f in faces]
    used = np.array(sorted({i for f in faces for i in f}))
    P = V[used]
    out = []
    for f in faces:
        nf = []; first = None
        for l in loops_of(f):
            if first is not None: nf.append(first)        # keep the multi-loop encoding: close the previous loop
            first = l[0]
            for a, b in zip(l, l[1:] + l[:1]):
                nf.append(a)
                d = V[b] - V[a]; L2 = d @ d
                if L2 < tol * tol: continue
                t = (P - V[a]) @ d / L2
                off = np.linalg.norm(P - V[a] - np.outer(t, d), axis=1)
                on = np.where((t > 1e-6) & (t < 1 - 1e-6) & (off < tol))[0]
                for k in on[np.argsort(t[on])]:
                    if used[k] not in (a, b): nf.append(int(used[k]))
        if len(loops_of(f)) > 1: nf.append(first)
        out.append(nf)
    return out


def drop_covered(V, faces, tol=1e-4):
    """Remove faces lying entirely inside a larger coplanar face (7.0-record cope ends: the full end outline plus
    duplicate flange-end patches that leave dangling edges)."""
    from shapely.geometry import Polygon
    info = []
    for k, f in enumerate(faces):
        ls = loops_of(f)
        if not ls: info.append(None); continue
        P = V[ls[0]]; c = P.mean(0)
        n = sum(np.cross(P[i] - c, P[(i + 1) % len(P)] - c) for i in range(len(P)))
        if np.linalg.norm(n) < 1e-12: info.append(None); continue
        n = n / np.linalg.norm(n); n = n if max(n, key=abs) > 0 else -n       # orientation-free plane key
        u = np.cross(n, [1, 0, 0] if abs(n[0]) < 0.9 else [0, 1, 0]); u /= np.linalg.norm(u); v = np.cross(n, u)
        try:
            poly = Polygon([(p @ u, p @ v) for p in V[ls[0]]]).buffer(0)
        except Exception:
            info.append(None); continue
        info.append((tuple(np.round(n, 4)), round(float(n @ c), 3), poly, u, v))
    drop = set()
    # the same face stored twice: a plain duplicate (its edges then have 3 users, Saralee W18x97 end faces) -> keep
    # one; two bodies touching face to face (4 users) -> internal wall, drop both
    import collections
    use = collections.Counter()
    for f in faces:
        for l in loops_of(f):
            for a, b in zip(l, l[1:] + l[:1]): use[(min(a, b), max(a, b))] += 1
    seen = {}
    for k, f in enumerate(faces):
        key = tuple(sorted(set(f)))
        if key in seen and len(key) >= 3:
            l = loops_of(f)[0]
            n = max(use[(min(a, b), max(a, b))] for a, b in zip(l, l[1:] + l[:1]))
            drop.update((k, seen[key]) if n >= 4 else (k,))
        else:
            seen[key] = k
    # repair stage only: a single-loop face that repeats the outer loop of a ring face on the same plane is a cap over a
    # hollow end (7.1xx pipe ends stored as ring + full disk + inner disk: their edges had 3 users and the pipe fell back)
    outer_of = {}
    for k, f in enumerate(faces if _CLEAN_LOOPS else ()):
        ls = loops_of(f)
        if len(ls) > 1 and info[k] is not None:
            outer_of.setdefault((info[k][0], info[k][1], frozenset(ls[0])), k)
    for k, f in enumerate(faces if outer_of else ()):
        ls = loops_of(f)
        if len(ls) == 1 and info[k] is not None and (info[k][0], info[k][1], frozenset(ls[0])) in outer_of:
            drop.add(k)
    for i, a in enumerate(info):
        if i in drop: continue
        if a is None: continue
        for j, b in enumerate(info):
            if i == j or b is None or j in drop or a[:2] != b[:2]: continue
            if a[2].area < b[2].area and a[2].within(b[2].buffer(tol * 10)):
                drop.add(i); break
    return [f for k, f in enumerate(faces) if k not in drop]


SLIVER_W = 3e-3      # in: faces narrower than this (2 x area / perimeter) hanging on free / over-used edges are flaps
PLANE_TOL = 1e-3     # in: vertex distance from a plane for faces treated as coplanar by merge_coplanar()
LAST_REPAIR = ""     # set by solid(): which repair pass produced the solid ("" = as stored / conform / drop_covered)


def _newell(P):
    c = P.mean(0)
    return sum(np.cross(P[k] - c, P[(k + 1) % len(P)] - c) for k in range(len(P))), c


def _edge_use(faces):
    import collections
    E = collections.Counter()
    for f in faces:
        for l in loops_of(f):
            for a, b in zip(l, l[1:] + l[:1]):
                if a != b:
                    E[(min(a, b), max(a, b))] += 1
    return E


def drop_slivers(V, faces, wmax=SLIVER_W):
    """Remove zero-width flaps: single-loop faces narrower than wmax (2 x area / perimeter) with an edge that is not
    shared by exactly two faces. P545 7.135 PL3/8x21 1/4: a 0.0009-in wide face hinged on a cope edge gave that edge 3
    users and left 3 free edges, so the plate fell back to an approximate outline. A flap encloses no volume; the
    other faces are kept as stored (if they do not close without it, the piece still falls back)."""
    E = _edge_use(faces)
    out = []
    for f in faces:
        ls = loops_of(f)
        if len(ls) == 1:
            l = ls[0]; P = V[l]
            nv, _ = _newell(P)
            per = sum(np.linalg.norm(P[(k + 1) % len(P)] - P[k]) for k in range(len(P)))
            if per > 0 and np.linalg.norm(nv) / per < wmax and \
                    any(E[(min(a, b), max(a, b))] != 2 for a, b in zip(l, l[1:] + l[:1]) if a != b):
                continue
        out.append(f)
    return out


WELD_TOL = 1e-3      # in: = the sewing tolerance; weld() merges vertices closer than this


def weld(V, faces, tol=WELD_TOL):
    """Merge vertices closer than the sewing tolerance (conform() merges at 1e-4 in only). 7.312 DUPONT W8x13: cope
    corners stored 0.0002-0.0007 in apart left 10 free edges around 5-18 um slivers. No vertex moves by more than tol;
    faces that collapse are skipped by the face builder."""
    from scipy.spatial import cKDTree
    used = sorted({i for f in faces for i in f})
    if len(used) < 2:
        return faces
    par = list(range(len(used)))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]; a = par[a]
        return a
    for i, j in cKDTree(np.asarray(V)[used]).query_pairs(tol):
        par[find(i)] = find(j)
    rep = {used[i]: used[find(i)] for i in range(len(used))}
    if all(rep[i] == i for i in used):
        return faces
    return [[rep[i] for i in f] for f in faces]


def drop_isolated(faces):
    """Remove faces that share no edge with any other face (every edge used once): they bound no volume. 8.004 TEMP JOB
    BPL12GAx60 / 7.425 RH Jacksonville BPL3/16x1 1/2: a bent plate's mid-surface marker faces carry kind 7 except one
    stored with kind 0, which was built as a real face, left 4 free edges and sent 312 + 202 placements to the
    approximate builder. The stored boundary faces are unchanged (if they do not close, the piece still falls back)."""
    E = _edge_use(faces)
    return [f for f in faces
            if not all(E[(min(a, b), max(a, b))] == 1 for l in loops_of(f) for a, b in zip(l, l[1:] + l[:1]) if a != b)]


def merge_coplanar(V, faces, tol=PLANE_TOL):
    """Overlapping coplanar faces of the same orientation -> one face, their union. 7.1xx-7.4xx cope / notch end faces
    are stored as overlapping patches (P545 7.135 PL1/2x13 1/2: side x = 7 as y -13.5..-7.5 and y -11.5..-7; C6x8.2
    cope end as two patches), whose overlap edges then have 3 users. The union covers exactly the points of the stored
    patches: its outline vertices are the patches' own vertices, plus any crossing point of two patch edges (appended
    to V). Multi-loop faces are left as they are. Returns (V, faces); faces unchanged if nothing overlaps."""
    from shapely.geometry import Polygon, MultiPolygon
    from shapely.geometry.polygon import orient
    from shapely.ops import unary_union
    info = []
    for f in faces:
        ls = loops_of(f)
        if len(ls) != 1:
            info.append(None); continue
        nv, c = _newell(V[ls[0]])
        a2 = np.linalg.norm(nv)
        info.append((ls[0], nv / a2, c, a2 / 2, nv) if a2 > 1e-12 else None)
    idx = [k for k in range(len(faces)) if info[k] is not None]
    if len(idx) < 2:
        return V, faces
    N = np.array([info[k][1] for k in idx]); C = np.array([info[k][2] for k in idx])
    taken = np.zeros(len(idx), bool); clusters = []
    for oi in np.argsort([-info[k][3] for k in idx]):
        if taken[oi]:
            continue
        k = idx[oi]; n = info[k][1]; d = float(n @ info[k][2])
        taken[oi] = True; mem = [k]
        # facing the same way and centred on k's plane; then every vertex on it (within tol)
        for cj in np.where(~taken & (N @ n > 0.5) & (np.abs(C @ n - d) <= tol))[0]:
            lj, _, _, _, nvj = info[idx[cj]]
            if np.abs(V[lj] @ n - d).max() <= tol and nvj @ n > 0.5 * np.linalg.norm(nvj):
                mem.append(idx[cj]); taken[cj] = True
        if len(mem) > 1:
            clusters.append((n, d, mem))
    if not clusters:
        return V, faces
    V = np.asarray(V, float); extra = []; drop = set(); new = []
    for n, d, mem in clusters:
        u = np.cross(n, [1, 0, 0] if abs(n[0]) < 0.9 else [0, 1, 0]); u /= np.linalg.norm(u); w = np.cross(n, u)
        polys = {}
        for k in mem:
            try:
                pg = Polygon([(p @ u, p @ w) for p in V[info[k][0]]]).buffer(0)
            except Exception:
                pg = None
            if pg is not None and not pg.is_empty and pg.area > 0:
                polys[k] = pg
        ks = list(polys)
        adj = {k: set() for k in ks}
        for x in range(len(ks)):
            for y in range(x + 1, len(ks)):
                if polys[ks[x]].intersection(polys[ks[y]]).area > 1e-6:
                    adj[ks[x]].add(ks[y]); adj[ks[y]].add(ks[x])
        seen = set()
        for k0 in ks:
            if k0 in seen or not adj[k0]:
                continue
            comp, st = [], [k0]
            while st:
                x = st.pop()
                if x in seen: continue
                seen.add(x); comp.append(x); st.extend(adj[x])
            U = unary_union([polys[k] for k in comp])
            parts = list(U.geoms) if isinstance(U, MultiPolygon) else [U]
            src = sorted({i for k in comp for i in info[k][0]})
            S2 = np.array([(V[i] @ u, V[i] @ w) for i in src])
            faces_c = []
            ok = True
            for pg in parts:
                if pg.geom_type != "Polygon" or pg.is_empty:
                    ok = False; break
                pg = orient(pg, 1.0)                     # exterior counter-clockwise in (u, w): normal +n
                loops = []
                for ring in [pg.exterior] + list(pg.interiors):
                    lp = []
                    for x, y in list(ring.coords)[:-1]:
                        dd = np.abs(S2 - (x, y)).max(1)
                        i = int(dd.argmin())
                        if dd[i] <= tol:
                            vi = src[i]
                        else:                            # crossing point of two patch edges, on the plane
                            vi = len(V) + len(extra); extra.append(n * d + x * u + y * w)
                        if not lp or lp[-1] != vi:
                            lp.append(vi)
                    if len(lp) > 1 and lp[0] == lp[-1]:
                        lp.pop()
                    if len(lp) >= 3:
                        loops.append(lp)
                if not loops:
                    ok = False; break
                f = []
                for lp in loops:
                    f += lp + [lp[0]]
                faces_c.append(f if len(loops) > 1 else loops[0])
            if ok and faces_c:
                drop.update(comp); new += faces_c
    if not drop:
        return V, faces
    if extra:
        V = np.vstack([V, np.array(extra)])
    return V, [f for k, f in enumerate(faces) if k not in drop] + new


def _passes(V, faces, M=None, o=None):
    """The v5.4 sequence: faces as stored, conform() (merge vertices, split T-junctions), drop_covered()."""
    sh = _solid_parts(V, faces, M, o)
    if sh is None:
        F2 = conform(V, faces)
        sh = _solid_parts(V, F2, M, o)
        if sh is None:
            F3 = drop_covered(V, F2)
            if len(F3) < len(F2):
                sh = _solid_parts(V, conform(V, F3), M, o)
    return sh


def _repaired(V, faces, M=None, o=None):
    """Repair stage of solid(), run only when the v5.4 passes leave the faces open (pieces that built in v5.4 are built
    exactly as before). Uses only the faces the piece file stores:
      1. keyhole / spike loops split, ring caps dropped (draft v5.5 loops_of / drop_covered), v5.4 passes again;
      2. faces sharing no edge dropped (drop_isolated), zero-width flaps dropped (drop_slivers) and overlapping
         coplanar patches merged (merge_coplanar), with the loops split as in 1, then as stored;
      3. as 2 after welding vertices closer than the sewing tolerance (weld, 0.001 in).
    Returns a closed valid solid or None; LAST_REPAIR names what was needed."""
    global _CLEAN_LOOPS, LAST_REPAIR

    def split_any(F):                                    # does the keyhole / spike split change any loop of F?
        global _CLEAN_LOOPS
        _CLEAN_LOOPS = False; raw = [loops_of(f) for f in F]
        _CLEAN_LOOPS = True
        return any(loops_of(f) != r for f, r in zip(F, raw))
    try:
        ks = split_any(faces) or split_any(conform(V, faces))
        _CLEAN_LOOPS = True
        sh = _passes(V, faces, M, o)
        if sh is not None:
            LAST_REPAIR = "keyhole / spike loops split" if ks else "ring caps over hollow ends dropped"
            return sh
        for clean, welded in [(c, w) for w in (False, True) for c in ((True, False) if ks else (False,))]:
            _CLEAN_LOOPS = clean
            F1 = weld(V, faces) if welded else faces
            if welded and F1 is faces:
                continue
            F2 = conform(V, F1)
            F3 = drop_isolated(F2)
            F4 = drop_slivers(V, F3)
            V5, F5 = merge_coplanar(V, F4)
            if len(F4) == len(F2) and F5 is F4 and not welded:
                continue
            sh = _passes(V5, F5, M, o)
            if sh is not None:
                LAST_REPAIR = " + ".join(x for x, y in (("vertices within 0.001 in welded", welded),
                                                         ("keyhole / spike loops split", clean),
                                                         ("isolated faces dropped", len(F3) < len(F2)),
                                                         ("zero-width faces dropped", len(F4) < len(F3)),
                                                         ("overlapping coplanar faces merged", F5 is not F4)) if y)
                return sh
        return None
    finally:
        _CLEAN_LOOPS = False


REPAIR_MAX_FACES = 5000   # larger face sets skip the repair stage (time bound)


def solid(V, faces, M=None, o=None, repair=False):
    """Sew planar polygon faces (world transform o + M.T @ v, inches -> mm) into a solid (a compound of solids for
    multi-body pieces), or None. Retries with repair passes: conform() (merge vertices, split T-junctions), then
    also drop_covered() (redundant coplanar patches); with repair=True (steel pieces, to_step2.brep_placed) then the
    _repaired() stage (keyhole / spike loops, isolated faces, zero-width flaps, overlapping coplanar patches).
    brep.LAST_REPAIR names the repair-stage fix used ("" if none)."""
    global LAST_REPAIR
    LAST_REPAIR = ""
    try:
        sh = _passes(V, faces, M, o)
        if sh is None and repair and len(faces) <= REPAIR_MAX_FACES:
            sh = _repaired(V, faces, M, o)
    except Exception:
        sh = None
    return sh


def _solid_parts(V, faces, M=None, o=None):
    parts = bodies(faces)
    if len(parts) > 1:
        out = [_solid(V, p, M, o) for p in parts]
        if any(s is None for s in out):
            return None
        from OCP.TopoDS import TopoDS_Compound
        from OCP.BRep import BRep_Builder
        c = TopoDS_Compound(); bb = BRep_Builder(); bb.MakeCompound(c)
        for s in out: bb.Add(c, s)
        return c
    return _solid(V, faces, M, o)


def _solid(V, faces, M=None, o=None):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid
    from OCP.gp import gp_Pnt
    from OCP.TopoDS import TopoDS
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.ShapeFix import ShapeFix_Solid, ShapeFix_Face
    W = V if M is None else np.array([o + M.T @ v for v in V])

    def wire(idx):
        poly = BRepBuilderAPI_MakePolygon()
        for i in idx: poly.Add(gp_Pnt(*(W[i] * MM)))
        poly.Close()
        return poly.Wire() if poly.IsDone() else None

    sew = BRepBuilderAPI_Sewing(1e-3 * MM)
    n = 0
    for f in faces:
        ls = loops_of(f)
        if not ls: continue
        ls.sort(key=lambda l: -_area(W[l]))
        w0 = wire(ls[0])
        if w0 is None: continue
        mf = BRepBuilderAPI_MakeFace(w0, True)
        if not mf.IsDone():
            # OCC's plane fit rejects some planar loops (collinear leading points, signed zeros: Centene W18x40,
            # Saralee bent plates): give it the plane explicitly (Newell normal through the centroid)
            P = W[ls[0]] * MM; c = P.mean(0)
            nrm = sum(np.cross(P[i] - c, P[(i + 1) % len(P)] - c) for i in range(len(P)))
            if np.linalg.norm(nrm) < 1e-9: continue
            nrm = nrm / np.linalg.norm(nrm)
            from OCP.gp import gp_Pln, gp_Dir
            # points projected exactly onto the plane (a face on an explicit plane with off-plane vertices read back
            # invalid once placed in an assembly: SCHUCKERS C12x20.7, PIPE 1 1/2)
            poly = BRepBuilderAPI_MakePolygon()
            for q in P - np.outer((P - c) @ nrm, nrm): poly.Add(gp_Pnt(*q))
            poly.Close()
            if not poly.IsDone(): continue
            mf = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(*c), gp_Dir(*nrm)), poly.Wire(), True)
            if not mf.IsDone(): continue
            for l in ls[1:]:
                Q = W[l] * MM; pl = BRepBuilderAPI_MakePolygon()
                for q in Q - np.outer((Q - c) @ nrm, nrm): pl.Add(gp_Pnt(*q))
                pl.Close()
                if pl.IsDone(): mf.Add(pl.Wire())
            fx0 = ShapeFix_Face(mf.Face()); fx0.FixOrientation(); fx0.Perform()
            sew.Add(fx0.Face()); n += 1
            continue
        if len(ls) > 1:
            for l in ls[1:]:
                w = wire(l)
                if w is not None: mf.Add(w)
            fx = ShapeFix_Face(mf.Face()); fx.FixOrientation(); fx.Perform(); face = fx.Face()
        else:
            face = mf.Face()
        sew.Add(face); n += 1
    if n < 4:
        return None
    try:
        sew.Perform()
        if sew.NbFreeEdges():
            return None                                   # open shell: not a closed body
        # one solid per closed shell (joists: separate chord angles, seats, webs in one piece file)
        out = []
        ex = TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL)
        while ex.More():
            ms = BRepBuilderAPI_MakeSolid(TopoDS.Shell(ex.Current()))
            if not ms.IsDone(): return None
            fx = ShapeFix_Solid(ms.Solid()); fx.Perform(); sh = fx.Solid()
            if not BRepCheck_Analyzer(sh).IsValid(): return None
            out.append(sh); ex.Next()
        if not out:
            return None
        if len(out) == 1:
            return out[0]
        from OCP.TopoDS import TopoDS_Compound
        from OCP.BRep import BRep_Builder
        c = TopoDS_Compound(); bb = BRep_Builder(); bb.MakeCompound(c)
        for s in out: bb.Add(c, s)
        return c
    except Exception:
        return None


def boundary_loops(faces):
    """Closed chains of edges used by exactly one face (the open rims of a body), as vertex-index loops; None when a
    rim branches or does not close."""
    import collections
    E = collections.Counter()
    for f in faces:
        for l in loops_of(f):
            for a, b in zip(l, l[1:] + l[:1]):
                E[(min(a, b), max(a, b))] += 1
    if any(c > 2 for c in E.values()):
        return None                                   # non-manifold edges: not a body with open rims
    adj = collections.defaultdict(list)
    for (a, b), c in E.items():
        if c == 1:
            adj[a].append(b); adj[b].append(a)
    if not adj or any(len(v) != 2 for v in adj.values()):
        return None
    seen = set(); loops = []
    for s0 in list(adj):
        if s0 in seen:
            continue
        loop = [s0]; seen.add(s0); prev, cur = None, s0
        while True:
            nxt = [x for x in adj[cur] if x != prev]
            if not nxt:
                return None
            n = nxt[0]
            if n == s0:
                break
            if n in seen:
                return None
            loop.append(n); seen.add(n); prev, cur = cur, n
        loops.append(loop)
    return loops


def rims_only(faces):
    """The body's only defect is open rims: every edge is used by one or two faces and the once-used edges form
    simple closed loops."""
    return bool(boundary_loops(faces))


def face_set(V, faces):
    """The stored faces as a compound of individually valid planar faces: no sewing, nothing filled or closed. The
    surface form of an imported reference mesh whose sewn shell fails BRepCheck (data-3 jfkf 7.331: 624 of 624
    placements of 47 such parts were left out). Returns the compound or None when no face is valid."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRep import BRep_Builder
    from OCP.gp import gp_Pnt
    bb = BRep_Builder(); comp = TopoDS_Compound(); bb.MakeCompound(comp); n = 0
    for f in faces:
        for l in loops_of(f)[:1]:
            poly = BRepBuilderAPI_MakePolygon()
            for i in l: poly.Add(gp_Pnt(*(V[i] * MM)))
            poly.Close()
            if not poly.IsDone(): continue
            mf = BRepBuilderAPI_MakeFace(poly.Wire(), True)
            if mf.IsDone() and BRepCheck_Analyzer(mf.Face()).IsValid():
                bb.Add(comp, mf.Face()); n += 1
    return comp if n else None


def shell(V, faces):
    """Faces sewn as stored, without requiring a closed body: imported reference meshes (DWF) are often open
    surfaces. Returns the sewn shape (shells / faces) or None."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing
    from OCP.gp import gp_Pnt
    sew = BRepBuilderAPI_Sewing(1e-3 * MM); n = 0
    for f in faces:
        for l in loops_of(f)[:1]:
            poly = BRepBuilderAPI_MakePolygon()
            for i in l: poly.Add(gp_Pnt(*(V[i] * MM)))
            poly.Close()
            if not poly.IsDone(): continue
            mf = BRepBuilderAPI_MakeFace(poly.Wire(), True)
            if mf.IsDone(): sew.Add(mf.Face()); n += 1
    if n == 0:
        return None
    try:
        sew.Perform()
        return sew.SewedShape()
    except Exception:
        return None

