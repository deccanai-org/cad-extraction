"""lumpsplit - split one faceted 'closed shell' into the closed solids it really is (pure python, no kernel).

Why: ISO 10303-42 closed_shell is a connected_face_set (one connected lump). SDS/2 IFC exports (via ST-Developer) put
a whole bolt (head + washers + shank + nut), a shear stud (head + shank) or a fillet weld (3-4 mitred / overlapping
triangular prisms) into ONE IfcClosedShell. ifc2step copied that into one STEP CLOSED_SHELL. OpenCASCADE's read-time
healing (ShapeFix_Shell / ShapeFix_Solid) then splits the shell and guesses which lump is a void of which: touching or
interpenetrating lumps get nested, the 'void' is reversed and the solid volume goes negative (or a non-manifold weld
is shredded into dozens of fragment solids, some inside-out / invalid).

decompose(loops_per_face, xyz) -> (components, info); component = {'faces': [face index], 'vol', 'closed', 'oriented'}
  loops_per_face : per face, list of loops, each loop a list of vertex keys (orderable + hashable: the writer's
                   point entity ids), loop orientation as written (outer loop CCW seen from outside)
  xyz            : vertex key -> (x, y, z)
 1. edge-lumps: faces joined across any shared edge (vertex-id pair), exactly how OpenCASCADE's StepToTopoDS shares
    edges. Disconnected lumps (bolt head / washer / shank / nut, stud head / shank) are separate solids;
 2. inside an edge-lump, coincident face pairs with opposite orientation (internal mitre faces between glued weld
    prisms, faces shared by touching bolt parts) are dropped - accepted only if every remaining piece is a closed
    shell, so a double-sided zero-volume sheet (a source defect) is left exactly as written;
 3. an edge used by more than two faces with balanced orientation is resolved by radial ordering (each half-edge is
    paired with the next face met rotating into the solid's interior); if that would leave an open piece, the lump
    stays whole;
 4. closed lumps are written as their own solid; all open lumps (source defects) stay together in one shell, as
    written before, so nothing that was not provably closed changes;
 5. a closed, consistently oriented lump with negative signed volume inside (bbox) a positive one is kept in that
    lump's shell (genuine void). Nothing is ever reversed or re-oriented: OpenCASCADE does that per lump on read
    (an ORIENTED_FACE(.F.) inside a FACETED_BREP shell is dropped by the OCC 7.x/8 reader - tested - so the writer
    must not use it).
"""
import math
from collections import defaultdict


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    l = math.sqrt(_dot(a, a))
    return (a[0] / l, a[1] / l, a[2] / l) if l > 1e-300 else None


def newell(loop, xyz):
    nx = ny = nz = 0.0
    n = len(loop)
    for i in range(n):
        x1, y1, z1 = xyz[loop[i]]
        x2, y2, z2 = xyz[loop[(i + 1) % n]]
        nx += (y1 - y2) * (z1 + z2); ny += (z1 - z2) * (x1 + x2); nz += (x1 - x2) * (y1 + y2)
    return _norm((nx, ny, nz))


def signed_volume(faces, loops_per_face, xyz):
    v = 0.0
    for fi in faces:
        for lp in loops_per_face[fi]:
            if len(lp) < 3:
                continue
            p0 = xyz[lp[0]]
            for i in range(1, len(lp) - 1):
                v += _dot(p0, _cross(xyz[lp[i]], xyz[lp[i + 1]]))
    return v / 6.0


def _bbox(faces, loops_per_face, xyz):
    P = [xyz[k] for fi in faces for lp in loops_per_face[fi] for k in lp]
    return [min(p[c] for p in P) for c in range(3)] + [max(p[c] for p in P) for c in range(3)]


def _opposite_pairs(loops_per_face, faces):
    """coincident faces with opposite orientation (same cyclic vertex sequence, reversed) -> {face: partner}"""
    canon = {}
    for fi in faces:
        loops = loops_per_face[fi]
        if len(loops) != 1 or len(loops[0]) < 3:
            continue
        lp = loops[0]
        k = frozenset(lp)
        if len(k) != len(lp):
            continue
        i0 = lp.index(min(lp))
        canon.setdefault(k, []).append((fi, tuple(lp[i0:] + lp[:i0])))
    partner = {}
    for lst in canon.values():
        if len(lst) < 2:
            continue
        for a in range(len(lst)):
            if lst[a][0] in partner:
                continue
            fa = lst[a][1]
            rev = (fa[0],) + tuple(reversed(fa[1:]))
            for b in range(a + 1, len(lst)):
                if lst[b][0] not in partner and lst[b][1] == rev:
                    partner[lst[a][0]] = lst[b][0]; partner[lst[b][0]] = lst[a][0]
                    break
    return partner


def _half_edges(loops_per_face, faces):
    he = defaultdict(list)                     # undirected edge -> [(face, from, to)]
    for fi in faces:
        for lp in loops_per_face[fi]:
            n = len(lp)
            for i in range(n):
                u, w = lp[i], lp[(i + 1) % n]
                if u != w:
                    he[(u, w) if u < w else (w, u)].append((fi, u, w))
    return he


class _UF:
    def __init__(self, items):
        self.p = {i: i for i in items}

    def find(self, x):
        p = self.p
        while p[x] != x:
            p[x] = p[p[x]]; x = p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb

    def groups(self):
        g = defaultdict(list)
        for i in self.p:
            g[self.find(i)].append(i)
        return list(g.values())


def _closed(faces, loops_per_face):
    cnt = defaultdict(int); dirs = defaultdict(int)
    for fi in faces:
        for lp in loops_per_face[fi]:
            n = len(lp)
            for i in range(n):
                u, w = lp[i], lp[(i + 1) % n]
                if u == w:
                    continue
                k = (u, w) if u < w else (w, u)
                cnt[k] += 1; dirs[k] += 1 if k == (u, w) else -1
    closed = all(v == 2 for v in cnt.values())
    return closed, closed and all(v == 0 for v in dirs.values())


def _split(faces, loops_per_face, xyz, info):
    """solids of one edge-connected face set: join across 2-use edges (any orientation: OpenCASCADE shares the edge
    and re-orients, e.g. SDS/2 tube inner walls written inside-out); at an edge with more uses and balanced
    orientation pair each half-edge with the next face met rotating into the solid's interior (radial order).
    If that yields more than one piece and any piece is open, the set is kept whole (as it was written)."""
    uf = _UF(faces)
    nrm = {}
    for e, uses in _half_edges(loops_per_face, faces).items():
        if len(uses) < 2:
            continue
        if len(uses) == 2:
            uf.union(uses[0][0], uses[1][0]); continue
        info['nonmanifold_edges'] += 1
        d = _norm(_sub(xyz[e[1]], xyz[e[0]]))
        fwd = sum(1 for x in uses if x[1] == e[0])
        ang = []
        if d is not None and 2 * fwd == len(uses):
            ref = ref2 = None
            for (fi, u, w) in uses:
                if fi not in nrm:
                    nrm[fi] = newell(loops_per_face[fi][0], xyz)
                n = nrm[fi]
                if n is None:
                    break
                t = _norm(_cross(n, d) if u == e[0] else _cross(d, n))   # in-face direction away from the edge
                if t is None:
                    break
                s = 1.0 if _dot(_cross(t, (-n[0], -n[1], -n[2])), d) > 0 else -1.0   # sense from t into the solid (-n)
                if ref is None:
                    ref = t; ref2 = _cross(d, t)
                ang.append((fi, u, w, math.atan2(_dot(t, ref2), _dot(t, ref)), s))
        if len(ang) != len(uses):
            for x in uses[1:]:
                uf.union(uses[0][0], x[0])      # unbalanced / degenerate non-manifold edge: keep together
            continue
        info['radial_edges'] += 1
        for (fi, u, w, th, s) in ang:
            best, bd = None, 9.0
            for (fj, uj, wj, thj, sj) in ang:
                if fj == fi or not (uj == w and wj == u):
                    continue
                dth = (s * (thj - th)) % (2 * math.pi)
                if dth < 1e-9:
                    dth = 2 * math.pi
                if dth < bd:
                    best, bd = fj, dth
            if best is not None:
                uf.union(fi, best)
    parts = uf.groups()
    if len(parts) > 1 and not all(_closed(p, loops_per_face)[0] for p in parts):
        info['kept_whole'] += 1
        return [list(faces)]
    return parts


def decompose(loops_per_face, xyz):
    """-> (components, info). components: [{'faces': [face index], 'vol', 'closed', 'oriented'}]; faces not listed in
    any component are internal coincident opposite pairs that were dropped."""
    info = {'cancelled_faces': 0, 'nonmanifold_edges': 0, 'radial_edges': 0, 'kept_whole': 0, 'cancel_rejected': 0}
    nf = len(loops_per_face)
    # edge-lumps: faces joined across any shared edge
    uf = _UF(range(nf))
    for uses in _half_edges(loops_per_face, range(nf)).values():
        for x in uses[1:]:
            uf.union(uses[0][0], x[0])
    comps = []
    for lump in uf.groups():
        partner = _opposite_pairs(loops_per_face, lump)
        if partner:
            # internal faces (weld prisms glued on a mitre face, bolt parts sharing a face) cancel out; accepted only
            # when every remaining piece is a closed shell (a double-sided / zero-volume sheet is left as it is)
            rest = [f for f in lump if f not in partner]
            parts = _split(rest, loops_per_face, xyz, info) if rest else []
            if parts and all(_closed(p, loops_per_face)[0] for p in parts):
                info['cancelled_faces'] += len(lump) - len(rest)
                comps += parts
            else:
                info['cancel_rejected'] += 1
                comps.append(list(lump))
            continue
        comps += _split(lump, loops_per_face, xyz, info)
    # closed lumps become their own solids; every open lump (source defect: T-junctions, double-sided sheets,
    # missing faces) stays together in one shell exactly as before, so OpenCASCADE heals it the way it always did
    out = []; rest = []
    for c in comps:
        closed, oriented = _closed(c, loops_per_face)
        if not closed:
            rest += c; continue
        out.append({'faces': sorted(c), 'vol': signed_volume(c, loops_per_face, xyz), 'bbox': _bbox(c, loops_per_face, xyz),
                    'host': None, 'closed': True, 'oriented': oriented})
    if rest:
        info['open_lumps_kept_together'] = len(comps) - len(out)
        out.append({'faces': sorted(rest), 'vol': signed_volume(rest, loops_per_face, xyz), 'bbox': None,
                    'host': None, 'closed': False, 'oriented': False})
    # a closed, consistently oriented lump with negative volume inside a positive one is its void: same shell
    pos = [o for o in out if o['oriented'] and o['vol'] > 0]
    for o in out:
        if o['oriented'] and o['vol'] < 0:
            hosts = [p for p in pos if all(p['bbox'][q] <= o['bbox'][q] + 1e-9 for q in range(3)) and
                     all(p['bbox'][q + 3] >= o['bbox'][q + 3] - 1e-9 for q in range(3))]
            if hosts:
                o['host'] = min(hosts, key=lambda p: p['vol'])
    res = []
    for o in out:
        if o['host'] is not None:
            continue
        faces = list(o['faces']); vol = o['vol']
        for v in out:
            if v['host'] is o:
                faces += v['faces']; vol += v['vol']; info['voids_kept'] = info.get('voids_kept', 0) + 1
        res.append({'faces': faces, 'vol': vol, 'closed': o['closed'], 'oriented': o['oriented']})
    res.sort(key=lambda c: c['faces'][0])
    info['components'] = len(res)
    info['open_components'] = sum(1 for o in res if not o['closed'])
    return res, info
