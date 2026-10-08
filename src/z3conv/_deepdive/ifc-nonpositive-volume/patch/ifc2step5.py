#!/usr/bin/env python3
"""
ifc2step - convert IFC to STEP AP214 faceted_brep.

Two paths:
  mode=transcode : read IFC entity-level faceted geometry (IfcFacetedBrep,
                   IfcShellBasedSurfaceModel, IfcFaceBasedSurfaceModel,
                   IfcPolygonalFaceSet, IfcTriangulatedFaceSet), apply the
                   placement transform, emit STEP FACETED_BREP / POLY_LOOP
                   directly. No geometry kernel at all.
  mode=tess      : use ifcopenshell.geom triangulation iterator (multi
                   threaded) for every product, emit the same STEP.
  mode=hybrid    : transcode where possible, tess for the remainder.

Writes a JSON stats blob to <out>.stats.json
"""
import sys, os, json, time, math, argparse, datetime
import re as _re


def step_str(v, limit=120):
    """ISO 10303-21 string body, safe for OpenCASCADE: runs of apostrophes (Revit feet-inch names such as
    8'' come out of IFC as two quote characters) become one '"' (OCC 8.0.1's lexer rejects '''' inside a
    string and then crashes on the dangling references), a single apostrophe is doubled, backslash is escaped,
    non-ASCII is written as \\X2\\hhhh\\X0\\. Truncated before escaping so no escape is ever cut."""
    v = _re.sub("'{2,}", '"', str(v or ""))[:limit]
    out = []
    for ch in v:
        o = ord(ch)
        if ch == "'":
            out.append("''")
        elif ch == "\\":
            out.append("\\\\")
        elif 32 <= o < 127:
            out.append(ch)
        elif o < 0x10000 and o >= 32:
            out.append("\\X2\\%04X\\X0\\" % o)
        else:
            out.append("?")
    return "".join(out)

import ifcopenshell
import ifcopenshell.util.placement
import ifcopenshell.util.unit
try:
    import resource
except ImportError:  # Windows: only the RSS statistic is affected
    resource = None


def rss():
    if resource is None:
        return -1
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024

# ---------------------------------------------------------------- real fmt

def _r(v):
    # compact STEP REAL: must contain '.'
    if v == 0.0:
        return "0."
    s = "%.9g" % v
    if "e" in s or "E" in s:
        m, _, e = s.partition("e")
        if "." not in m:
            m += "."
        return m + "E" + str(int(e))
    if "." not in s:
        s += "."
    return s


class StepWriter:
    """Streaming STEP AP214 writer with entity dedup for points/directions."""

    def __init__(self, fh, name, length_unit_prefix, uncertainty):
        self.fh = fh
        self.buf = []
        self.buflen = 0
        self.n = 100  # next entity id
        self.pt_cache = {}
        self.dir_cache = {}
        self.n_pts = 0
        self.n_dirs = 0
        self.n_faces = 0
        self.n_parts = 0
        self.nodedup = False
        self.prec = 6
        self.noplane = False
        self.bb = [1e30, 1e30, 1e30, -1e30, -1e30, -1e30]
        self.sc = 1.0   # multiply incoming coords by this to get millimetres
        # z3 lump split: per face id the loops (point ids) as written + point coords, consumed by solids()
        self.split_lumps = True
        self._floops = {}
        self._fxyz = {}
        self.lump_stats = {}
        self._header(name, length_unit_prefix, uncertainty)

    # ---- low level
    def _w(self, s):
        self.buf.append(s)
        self.buflen += len(s)
        if self.buflen > 4 << 20:
            self.fh.write("".join(self.buf))
            self.buf = []
            self.buflen = 0

    def _id(self):
        self.n += 1
        return self.n

    def e(self, body):
        i = self._id()
        self._w("#%d=%s;\n" % (i, body))
        return i

    def flush(self):
        if self.buf:
            self.fh.write("".join(self.buf))
            self.buf = []
            self.buflen = 0

    # ---- header
    def _header(self, name, prefix, unc):
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        self._w("ISO-10303-21;\nHEADER;\n")
        self._w("FILE_DESCRIPTION((''),'2;1');\n")
        self._w("FILE_NAME('%s','%s',(''),(''),'ifc2step 1.0','ifcopenshell','');\n"
                % (step_str(name, 200), ts))
        self._w("FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 }'));\n")
        self._w("ENDSEC;\nDATA;\n")
        self.ctx_app = self.e("APPLICATION_CONTEXT('automotive design')")
        self.e("APPLICATION_PROTOCOL_DEFINITION('international standard',"
               "'automotive_design',2000,#%d)" % self.ctx_app)
        self.ctx_prod = self.e("PRODUCT_CONTEXT('',#%d,'mechanical')" % self.ctx_app)
        self.ctx_pdef = self.e("PRODUCT_DEFINITION_CONTEXT('part definition',#%d,'design')"
                               % self.ctx_app)
        u_len = self.e("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(%s,.METRE.))" % prefix)
        u_ang = self.e("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))")
        u_sol = self.e("(NAMED_UNIT(*)SOLID_ANGLE_UNIT()SI_UNIT($,.STERADIAN.))")
        unc_i = self.e("UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(%s),#%d,"
                       "'distance_accuracy_value','')" % (_r(unc), u_len))
        self.ctx_geom = self.e(
            "(GEOMETRIC_REPRESENTATION_CONTEXT(3)"
            "GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#%d))"
            "GLOBAL_UNIT_ASSIGNED_CONTEXT((#%d,#%d,#%d))"
            "REPRESENTATION_CONTEXT('',''))" % (unc_i, u_len, u_ang, u_sol))
        o = self.pt(0.0, 0.0, 0.0)
        dz = self.dir(0.0, 0.0, 1.0)
        dx = self.dir(1.0, 0.0, 0.0)
        self.origin_ax = self.e("AXIS2_PLACEMENT_3D('',#%d,#%d,#%d)" % (o, dz, dx))

    # ---- dedup primitives
    def new_scope(self):
        # bound memory: points are shared within a product, rarely across
        self.pt_cache = {}
        self._floops = {}
        self._fxyz = {}

    def pt(self, x, y, z):
        if self.sc != 1.0:
            x *= self.sc; y *= self.sc; z *= self.sc
        b = self.bb
        if x < b[0]: b[0] = x
        if y < b[1]: b[1] = y
        if z < b[2]: b[2] = z
        if x > b[3]: b[3] = x
        if y > b[4]: b[4] = y
        if z > b[5]: b[5] = z
        if self.nodedup:
            i = self._id()
            self._w("#%d=CARTESIAN_POINT('',(%s,%s,%s));\n"
                    % (i, _r(x), _r(y), _r(z)))
            self.n_pts += 1
            return i
        d = self.prec
        k = (round(x, d), round(y, d), round(z, d))
        i = self.pt_cache.get(k)
        if i is None:
            i = self._id()
            self._w("#%d=CARTESIAN_POINT('',(%s,%s,%s));\n"
                    % (i, _r(k[0]), _r(k[1]), _r(k[2])))
            self.pt_cache[k] = i
            self.n_pts += 1
        return i

    def dir(self, x, y, z):
        k = (round(x, 6), round(y, 6), round(z, 6))
        i = self.dir_cache.get(k)
        if i is None:
            i = self._id()
            self._w("#%d=DIRECTION('',(%s,%s,%s));\n"
                    % (i, _r(k[0]), _r(k[1]), _r(k[2])))
            self.dir_cache[k] = i
            self.n_dirs += 1
        return i

    # ---- geometry
    def plane_from_normal(self, nx, ny, nz, origin_id):
        nd = self.dir(nx, ny, nz)
        # deterministic ref direction orthogonal to n
        if abs(nx) < 0.9:
            ax, ay, az = 1.0, 0.0, 0.0
        else:
            ax, ay, az = 0.0, 1.0, 0.0
        rx = ay * nz - az * ny
        ry = az * nx - ax * nz
        rz = ax * ny - ay * nx
        rl = math.sqrt(rx * rx + ry * ry + rz * rz)
        if rl < 1e-12:
            rx, ry, rz, rl = 1.0, 0.0, 0.0, 1.0
        rd = self.dir(rx / rl, ry / rl, rz / rl)
        ax_i = self.e("AXIS2_PLACEMENT_3D('',#%d,#%d,#%d)" % (origin_id, nd, rd))
        return self.e("PLANE('',#%d)" % ax_i)

    def face(self, loops):
        """loops: list of (point_id_list, is_outer). Returns face id or None."""
        bounds = []
        normal = None
        written = []
        for pids, pts, outer in loops:
            # z4 fix: drop repeated points (zero-length edges, e.g. after 0.01 mm rounding) and loops that
            # enclose no area; OpenCASCADE 8.0.1 segfaults transferring such faces. Geometry is unchanged.
            cp, cq = [], []
            for p, q in zip(pids, pts):
                if cp and p == cp[-1]:
                    continue
                cp.append(p); cq.append(q)
            while len(cp) > 1 and cp[0] == cp[-1]:
                cp.pop(); cq.pop()
            if len(set(cp)) < 3:
                if outer:
                    self.n_degenerate = getattr(self, 'n_degenerate', 0) + 1
                    return None
                continue
            pids, pts = cp, cq
            if self.split_lumps:
                written.append(pids)
                for p, q in zip(pids, pts):
                    self._fxyz[p] = q
            lp = self.e("POLY_LOOP('',(%s))" % ",".join("#%d" % p for p in pids))
            bounds.append(self.e("%s('',#%d,.T.)"
                                 % ("FACE_OUTER_BOUND" if outer else "FACE_BOUND", lp)))
            if outer and normal is None:
                normal = newell(pts)
        if not bounds:
            return None
        if self.noplane:
            f = self.e("FACE('',(%s))" % ",".join("#%d" % b for b in bounds))
            self.n_faces += 1
            if self.split_lumps:
                self._floops[f] = written
            return f
        if normal is None:
            return None
        nx, ny, nz, org = normal
        pl = self.plane_from_normal(nx, ny, nz, self.pt(*org))
        f = self.e("FACE_SURFACE('',(%s),#%d,.T.)"
                   % (",".join("#%d" % b for b in bounds), pl))
        self.n_faces += 1
        if self.split_lumps:
            self._floops[f] = written
        return f

    def solid(self, face_ids, closed=True):
        if not face_ids:
            return None
        sh = self.e("%s('',(%s))" % ("CLOSED_SHELL" if closed else "OPEN_SHELL",
                                     ",".join("#%d" % f for f in face_ids)))
        if closed:
            return self.e("FACETED_BREP('',#%d)" % sh), True
        return sh, False

    def solids(self, face_ids):
        """closed faceted shell -> [FACETED_BREP id, ...], one per closed lump (z3: non_positive_volume_solids).
        A STEP closed_shell is a connected_face_set (ISO 10303-42): one lump per shell. SDS/2 IFC puts a whole bolt
        (head, washers, shank, nut), a shear stud (head + shank) or a mitred fillet weld (glued triangular prisms) in
        ONE IfcClosedShell; copied verbatim, OpenCASCADE's read-time healing splits the shell and nests touching /
        interpenetrating lumps as voids (negative or under-counted volume) or shreds the non-manifold weld into
        dozens of fragment solids (invalid, inside-out, duplicated). _split_lumps(): coincident opposite internal
        face pairs dropped where that leaves closed shells, each closed lump its own FACETED_BREP, open lumps kept
        together as before. Faces are never rewritten or re-oriented; a clean single lump is written as before."""
        if not face_ids:
            return []
        loops = [self._floops.pop(f, None) for f in face_ids]
        if not self.split_lumps or self.nodedup or any(l is None for l in loops) or len(face_ids) > 400000:
            return [self.solid(face_ids, True)[0]]
        try:
            comps, info = _split_lumps(loops, self._fxyz)
        except Exception:
            self.lump_stats["errors"] = self.lump_stats.get("errors", 0) + 1
            return [self.solid(face_ids, True)[0]]
        for k in ("cancelled_faces", "radial_edges", "cancel_rejected", "kept_whole", "open_lumps_kept_together", "voids_kept"):
            if info.get(k):
                self.lump_stats[k] = self.lump_stats.get(k, 0) + info[k]
        if len(comps) < 2 and not info["cancelled_faces"]:
            return [self.solid(face_ids, True)[0]]
        self.lump_stats["breps_split"] = self.lump_stats.get("breps_split", 0) + (len(comps) > 1)
        self.lump_stats["breps_written"] = self.lump_stats.get("breps_written", 0) + len(comps)
        return [self.solid([face_ids[i] for i in c["faces"]], True)[0] for c in comps]

    def part(self, name, items, faceted=True, pid=None, desc=None):
        """items: list of brep ids (faceted) or open shell ids. pid = source part id (IFC GlobalId) written as
        PRODUCT.id and desc = source class written as PRODUCT.description (z3: exact part mapping for grading)."""
        if not items:
            return
        nm = step_str(name or "part")
        p = self.e("PRODUCT('%s','%s','%s',(#%d))" % (step_str(pid, 64) if pid else nm, nm, step_str(desc or "", 64), self.ctx_prod))
        self.e("PRODUCT_RELATED_PRODUCT_CATEGORY('part','',(#%d))" % p)
        pdf = self.e("PRODUCT_DEFINITION_FORMATION('','',#%d)" % p)
        pd = self.e("PRODUCT_DEFINITION('design','',#%d,#%d)" % (pdf, self.ctx_pdef))
        pds = self.e("PRODUCT_DEFINITION_SHAPE('','',#%d)" % pd)
        kind = ("FACETED_BREP_SHAPE_REPRESENTATION" if faceted
                else "SHELL_BASED_SURFACE_MODEL_SHAPE_REPRESENTATION")
        if not faceted:
            sbsm = self.e("SHELL_BASED_SURFACE_MODEL('',(%s))"
                          % ",".join("#%d" % i for i in items))
            items = [sbsm]
            kind = "MANIFOLD_SURFACE_SHAPE_REPRESENTATION"
        rep = self.e("%s('%s',(#%d,%s),#%d)"
                     % (kind, nm, self.origin_ax,
                        ",".join("#%d" % i for i in items), self.ctx_geom))
        self.e("SHAPE_DEFINITION_REPRESENTATION(#%d,#%d)" % (pds, rep))
        self.n_parts += 1

    def close(self):
        self._w("ENDSEC;\nEND-ISO-10303-21;\n")
        self.flush()


def newell(pts):
    """Newell normal + centroid-ish origin for a polygon (list of (x,y,z))."""
    nx = ny = nz = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1, z1 = pts[i]
        x2, y2, z2 = pts[(i + 1) % n]
        nx += (y1 - y2) * (z1 + z2)
        ny += (z1 - z2) * (x1 + x2)
        nz += (x1 - x2) * (y1 + y2)
    l = math.sqrt(nx * nx + ny * ny + nz * nz)
    if l < 1e-12:
        return None
    return (nx / l, ny / l, nz / l, pts[0])


# ---------------------------------------------------------------- lump split (z3: non_positive_volume_solids)
# = _deepdive/ifc-nonpositive-volume/patch/lumpsplit.py (decompose -> _split_lumps), inlined: the kit stays one file
from collections import defaultdict as _ls_dd




def _ls_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _ls_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _ls_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _ls_norm(a):
    l = math.sqrt(_ls_dot(a, a))
    return (a[0] / l, a[1] / l, a[2] / l) if l > 1e-300 else None


def _ls_newell(loop, xyz):
    nx = ny = nz = 0.0
    n = len(loop)
    for i in range(n):
        x1, y1, z1 = xyz[loop[i]]
        x2, y2, z2 = xyz[loop[(i + 1) % n]]
        nx += (y1 - y2) * (z1 + z2); ny += (z1 - z2) * (x1 + x2); nz += (x1 - x2) * (y1 + y2)
    return _ls_norm((nx, ny, nz))


def _ls_signed_volume(faces, loops_per_face, xyz):
    v = 0.0
    for fi in faces:
        for lp in loops_per_face[fi]:
            if len(lp) < 3:
                continue
            p0 = xyz[lp[0]]
            for i in range(1, len(lp) - 1):
                v += _ls_dot(p0, _ls_cross(xyz[lp[i]], xyz[lp[i + 1]]))
    return v / 6.0


def _ls_bbox(faces, loops_per_face, xyz):
    P = [xyz[k] for fi in faces for lp in loops_per_face[fi] for k in lp]
    return [min(p[c] for p in P) for c in range(3)] + [max(p[c] for p in P) for c in range(3)]


def _ls_opposite_pairs(loops_per_face, faces):
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


def _ls_half_edges(loops_per_face, faces):
    he = _ls_dd(list)                     # undirected edge -> [(face, from, to)]
    for fi in faces:
        for lp in loops_per_face[fi]:
            n = len(lp)
            for i in range(n):
                u, w = lp[i], lp[(i + 1) % n]
                if u != w:
                    he[(u, w) if u < w else (w, u)].append((fi, u, w))
    return he


class _LsUF:
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
        g = _ls_dd(list)
        for i in self.p:
            g[self.find(i)].append(i)
        return list(g.values())


def _ls_closed(faces, loops_per_face):
    cnt = _ls_dd(int); dirs = _ls_dd(int)
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


def _ls_split(faces, loops_per_face, xyz, info):
    """solids of one edge-connected face set: join across 2-use edges (any orientation: OpenCASCADE shares the edge
    and re-orients, e.g. SDS/2 tube inner walls written inside-out); at an edge with more uses and balanced
    orientation pair each half-edge with the next face met rotating into the solid's interior (radial order).
    If that yields more than one piece and any piece is open, the set is kept whole (as it was written)."""
    uf = _LsUF(faces)
    nrm = {}
    for e, uses in _ls_half_edges(loops_per_face, faces).items():
        if len(uses) < 2:
            continue
        if len(uses) == 2:
            uf.union(uses[0][0], uses[1][0]); continue
        info['nonmanifold_edges'] += 1
        d = _ls_norm(_ls_sub(xyz[e[1]], xyz[e[0]]))
        fwd = sum(1 for x in uses if x[1] == e[0])
        ang = []
        if d is not None and 2 * fwd == len(uses):
            ref = ref2 = None
            for (fi, u, w) in uses:
                if fi not in nrm:
                    nrm[fi] = _ls_newell(loops_per_face[fi][0], xyz)
                n = nrm[fi]
                if n is None:
                    break
                t = _ls_norm(_ls_cross(n, d) if u == e[0] else _ls_cross(d, n))   # in-face direction away from the edge
                if t is None:
                    break
                s = 1.0 if _ls_dot(_ls_cross(t, (-n[0], -n[1], -n[2])), d) > 0 else -1.0   # sense from t into the solid (-n)
                if ref is None:
                    ref = t; ref2 = _ls_cross(d, t)
                ang.append((fi, u, w, math.atan2(_ls_dot(t, ref2), _ls_dot(t, ref)), s))
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
    if len(parts) > 1 and not all(_ls_closed(p, loops_per_face)[0] for p in parts):
        info['kept_whole'] += 1
        return [list(faces)]
    return parts


def _split_lumps(loops_per_face, xyz):
    """-> (components, info). components: [{'faces': [face index], 'vol', 'closed', 'oriented'}]; faces not listed in
    any component are internal coincident opposite pairs that were dropped."""
    info = {'cancelled_faces': 0, 'nonmanifold_edges': 0, 'radial_edges': 0, 'kept_whole': 0, 'cancel_rejected': 0}
    nf = len(loops_per_face)
    # edge-lumps: faces joined across any shared edge
    uf = _LsUF(range(nf))
    for uses in _ls_half_edges(loops_per_face, range(nf)).values():
        for x in uses[1:]:
            uf.union(uses[0][0], x[0])
    comps = []
    for lump in uf.groups():
        partner = _ls_opposite_pairs(loops_per_face, lump)
        if partner:
            # internal faces (weld prisms glued on a mitre face, bolt parts sharing a face) cancel out; accepted only
            # when every remaining piece is a closed shell (a double-sided / zero-volume sheet is left as it is)
            rest = [f for f in lump if f not in partner]
            parts = _ls_split(rest, loops_per_face, xyz, info) if rest else []
            if parts and all(_ls_closed(p, loops_per_face)[0] for p in parts):
                info['cancelled_faces'] += len(lump) - len(rest)
                comps += parts
            else:
                info['cancel_rejected'] += 1
                comps.append(list(lump))
            continue
        comps += _ls_split(lump, loops_per_face, xyz, info)
    # closed lumps become their own solids; every open lump (source defect: T-junctions, double-sided sheets,
    # missing faces) stays together in one shell exactly as before, so OpenCASCADE heals it the way it always did
    out = []; rest = []
    for c in comps:
        closed, oriented = _ls_closed(c, loops_per_face)
        if not closed:
            rest += c; continue
        out.append({'faces': sorted(c), 'vol': _ls_signed_volume(c, loops_per_face, xyz), 'bbox': _ls_bbox(c, loops_per_face, xyz),
                    'host': None, 'closed': True, 'oriented': oriented})
    if rest:
        info['open_lumps_kept_together'] = len(comps) - len(out)
        out.append({'faces': sorted(rest), 'vol': _ls_signed_volume(rest, loops_per_face, xyz), 'bbox': None,
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


# ---------------------------------------------------------------- transcode

FACETED_TYPES = ("IfcFacetedBrep", "IfcFacetedBrepWithVoids",
                 "IfcShellBasedSurfaceModel", "IfcFaceBasedSurfaceModel",
                 "IfcPolygonalFaceSet", "IfcTriangulatedFaceSet",
                 "IfcClosedShell", "IfcOpenShell")


def mat_apply(m, p):
    return (m[0][0] * p[0] + m[0][1] * p[1] + m[0][2] * p[2] + m[0][3],
            m[1][0] * p[0] + m[1][1] * p[1] + m[1][2] * p[2] + m[1][3],
            m[2][0] * p[0] + m[2][1] * p[1] + m[2][2] * p[2] + m[2][3])


IDENT = ((1.0, 0, 0, 0), (0, 1.0, 0, 0), (0, 0, 1.0, 0), (0, 0, 0, 1.0))


def mat_mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4))
                 for i in range(4))


def shell_faces(shell, m, w):
    """IfcConnectedFaceSet -> list of step face ids"""
    out = []
    for f in shell.CfsFaces:
        loops = []
        for b in f.Bounds:
            lp = b.Bound
            if not lp.is_a("IfcPolyLoop"):
                return None  # not purely faceted
            pts = [mat_apply(m, p.Coordinates) for p in lp.Polygon]
            if getattr(b, "Orientation", True) is False:
                pts = pts[::-1]
            pids = [w.pt(*p) for p in pts]
            loops.append((pids, pts, b.is_a("IfcFaceOuterBound") or len(f.Bounds) == 1))
        fid = w.face(loops)
        if fid:
            out.append(fid)
    return out


def item_to_step(item, m, w):
    """Return (list_of_items, faceted_bool) or None if unsupported."""
    t = item.is_a()
    if t in ("IfcFacetedBrep", "IfcFacetedBrepWithVoids"):
        fl = shell_faces(item.Outer, m, w)
        if fl is None:
            return None
        res = w.solids(fl)
        if t == "IfcFacetedBrepWithVoids":
            for v in item.Voids:
                vf = shell_faces(v, m, w)
                if vf:
                    sv = w.solid(vf, True)
                    if sv:
                        res.append(sv[0])
        return (res, True)
    if t == "IfcShellBasedSurfaceModel":
        shells = []
        for sh in item.SbsmBoundary:
            fl = shell_faces(sh, m, w)
            if fl is None:
                return None
            if fl:
                shells.append(w.e("OPEN_SHELL('',(%s))"
                                  % ",".join("#%d" % f for f in fl)))
        return (shells, False)
    if t == "IfcFaceBasedSurfaceModel":
        shells = []
        for sh in item.FbsmFaces:
            fl = shell_faces(sh, m, w)
            if fl is None:
                return None
            if fl:
                shells.append(w.e("OPEN_SHELL('',(%s))"
                                  % ",".join("#%d" % f for f in fl)))
        return (shells, False)
    if t in ("IfcPolygonalFaceSet", "IfcTriangulatedFaceSet"):
        coords = item.Coordinates.CoordList
        pids = [w.pt(*mat_apply(m, c)) for c in coords]
        faces = []
        if t == "IfcTriangulatedFaceSet":
            idx = item.CoordIndex
            polys = [list(tri) for tri in idx]
        else:
            polys = []
            for fa in item.Faces:
                polys.append(list(fa.CoordIndex))
        for poly in polys:
            ii = [p - 1 for p in poly]
            pts = [mat_apply(m, coords[k]) for k in ii]
            fid = w.face([([pids[k] for k in ii], pts, True)])
            if fid:
                faces.append(fid)
        if not faces:
            return None
        closed = (item.Closed is True) if hasattr(item, "Closed") else True
        if closed:
            return (w.solids(faces), True)
        s = w.solid(faces, False)
        return ([s[0]], False)
    if t == "IfcMappedItem":
        src = item.MappingSource
        tgt = item.MappingTarget
        mt = ifcopenshell.util.placement.get_axis2placement(src.MappingOrigin) \
            if hasattr(ifcopenshell.util.placement, "get_axis2placement") else None
        m2 = m
        try:
            import numpy as np
            om = ifcopenshell.util.placement.get_mappeditem_transformation(item)
            m2 = mat_mul(m, tuple(tuple(float(x) for x in row) for row in om))
        except Exception:
            return None
        allitems, fac = [], True
        for si in src.MappedRepresentation.Items:
            r = item_to_step(si, m2, w)
            if r is None:
                return None
            allitems += r[0]
            fac = fac and r[1]
        return (allitems, fac)
    return None


SKIP_TYPES = ("IfcOpeningElement", "IfcSpace", "IfcGrid", "IfcAnnotation",
              "IfcVirtualElement", "IfcOpeningStandardCase")


def run_transcode(f, w, stats, also_tess_leftovers=False):
    products = f.by_type("IfcProduct")
    done, skipped = 0, []
    n_norep = 0
    n_unsupported_items = 0
    t0 = time.time()
    nprod = len(products)
    for pn, pr in enumerate(products):
        if pn % 20000 == 0:
            sys.stderr.write("[transcode] %d/%d parts=%d faces=%d %.0fs rss=%dMB\n"
                             % (pn, nprod, w.n_parts, w.n_faces, time.time() - t0, rss()))
            sys.stderr.flush()
        if pr.is_a() in SKIP_TYPES:
            continue
        rep = getattr(pr, "Representation", None)
        if rep is None:
            n_norep += 1
            continue
        items = []
        for r in rep.Representations:
            if r.RepresentationIdentifier not in (None, "Body", "Facetation"):
                continue
            items += list(r.Items)
        if not items:
            n_norep += 1
            continue
        try:
            m = ifcopenshell.util.placement.get_local_placement(pr.ObjectPlacement)
            m = tuple(tuple(float(x) for x in row) for row in m)
        except Exception:
            m = IDENT
        w.new_scope()
        outs, faceted = [], True
        ok = True
        for it in items:
            r = item_to_step(it, m, w)
            if r is None:
                ok = False
                break
            outs += r[0]
            faceted = faceted and r[1]
        if not ok or not outs:
            n_unsupported_items += 1
            skipped.append(pr.id())
            continue
        nm = "%s_%s" % (pr.is_a(), pr.GlobalId if hasattr(pr, "GlobalId") else pr.id())
        if getattr(pr, "Name", None):
            nm = "%s" % pr.Name
        w.part(nm, outs, faceted, pid=getattr(pr, "GlobalId", None), desc=pr.is_a())
        done += 1
    stats["transcode_products"] = done
    stats["transcode_skipped"] = len(skipped)
    stats["transcode_no_body_rep"] = n_norep
    stats["transcode_unsupported"] = n_unsupported_items
    stats["transcode_coverage_pct"] = round(100.0 * done / max(1, done + len(skipped)), 1)
    stats["transcode_sec"] = round(time.time() - t0, 2)
    return skipped


# ---------------------------------------------------------------- tessellate

def run_tess(path, w, stats, only_ids=None, threads=0):
    import ifcopenshell.geom
    t0 = time.time()
    old_sc = w.sc
    w.sc = 1000.0  # ifcopenshell returns metres
    f = ifcopenshell.open(path)
    s = ifcopenshell.geom.settings()
    dfl = float(os.environ.get("DEFLECTION", "0") or 0)
    ang = float(os.environ.get("ANG_DEFLECTION", "0") or 0)
    applied = {}
    if dfl > 0:
        for k in ("mesher-linear-deflection", "deflection-tolerance"):
            try:
                s.set(k, dfl)
                applied[k] = dfl
            except Exception as e:
                applied[k] = "err"
    if ang > 0:
        for k in ("mesher-angular-deflection", "angular-tolerance"):
            try:
                s.set(k, ang)
                applied[k] = ang
            except Exception:
                applied[k] = "err"
    stats["deflection_settings"] = applied
    for key, val in (("use-world-coords", True), ("weld-vertices", True)):
        try:
            s.set(key, val)
        except Exception:
            try:
                s.set(getattr(s, key.upper().replace("-", "_")), val)
            except Exception:
                pass
    if threads <= 0:
        threads = os.cpu_count() or 4
    if only_ids is not None:
        els = [f.by_id(i) for i in only_ids]
        els = [e for e in els if e is not None]
        if not els:
            stats["tess_products"] = 0
            stats["tess_sec"] = 0
            return
        it = ifcopenshell.geom.iterator(s, f, threads, include=els)
    else:
        it = None
        try:
            ex = []
            for t in SKIP_TYPES:
                try:
                    ex += list(f.by_type(t))
                except Exception:
                    pass
            if ex:
                it = ifcopenshell.geom.iterator(s, f, threads, exclude=ex)
        except Exception as e:
            sys.stderr.write("[tess] exclude failed (%s), falling back\n" % e)
            it = None
        if it is None:
            it = ifcopenshell.geom.iterator(s, f, threads)
    n = 0
    if not it.initialize():
        w.sc = old_sc
        stats["tess_products"] = 0
        stats["tess_sec"] = round(time.time() - t0, 2)
        return
    while True:
        sh = it.get()
        if n % 5000 == 0:
            sys.stderr.write("[tess] %d %.0fs rss=%dMB\n" % (n, time.time()-t0, rss()))
            sys.stderr.flush()
        w.new_scope()
        g = sh.geometry
        vs = g.verts
        fs = g.faces
        pids = [w.pt(vs[i], vs[i + 1], vs[i + 2]) for i in range(0, len(vs), 3)]
        faces = []
        for i in range(0, len(fs), 3):
            a, b, c = fs[i], fs[i + 1], fs[i + 2]
            pts = [(vs[a * 3], vs[a * 3 + 1], vs[a * 3 + 2]),
                   (vs[b * 3], vs[b * 3 + 1], vs[b * 3 + 2]),
                   (vs[c * 3], vs[c * 3 + 1], vs[c * 3 + 2])]
            fid = w.face([([pids[a], pids[b], pids[c]], pts, True)])
            if fid:
                faces.append(fid)
        if faces:
            brs = w.solids(faces)
            w.part(sh.name or sh.guid, brs, True, pid=sh.guid, desc=getattr(sh, "type", None))
            n += 1
        if not it.next():
            break
    w.sc = old_sc
    stats["tess_products"] = n
    stats["tess_sec"] = round(time.time() - t0, 2)


UNIT_PREFIX = {0.001: ".MILLI.", 0.01: ".CENTI.", 1.0: "$", 0.1: ".DECI.",
               1000.0: ".KILO.", 1e-6: ".MICRO."}


def length_unit_name(f):
    try:
        for u in f.by_type("IfcUnitAssignment")[0].Units:
            if getattr(u, "UnitType", None) == "LENGTHUNIT":
                if u.is_a("IfcSIUnit"):
                    return "SI:%s%s" % (u.Prefix or "", u.Name)
                if u.is_a("IfcConversionBasedUnit"):
                    return "CONV:%s" % u.Name
    except Exception:
        pass
    return "unknown"


def length_unit(f):
    try:
        for u in f.by_type("IfcUnitAssignment")[0].Units:
            if u.is_a("IfcSIUnit") and u.UnitType == "LENGTHUNIT":
                p = u.Prefix
                return {"MILLI": ".MILLI.", "CENTI": ".CENTI.", "DECI": ".DECI.",
                        "KILO": ".KILO.", "MICRO": ".MICRO.", None: "$"}.get(p, "$")
    except Exception:
        pass
    return "$"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ifc")
    ap.add_argument("out")
    ap.add_argument("--mode", default="hybrid",
                    choices=["transcode", "tess", "hybrid"])
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--nodedup", action="store_true")
    ap.add_argument("--noplane", action="store_true")
    ap.add_argument("--prec", type=int, default=6)
    ap.add_argument("--gzip", action="store_true")
    a = ap.parse_args()

    stats = {"input": a.ifc, "mode": a.mode, "nodedup": a.nodedup,
             "noplane": a.noplane, "prec": a.prec,
             "in_bytes": os.path.getsize(a.ifc)}
    T0 = time.time()
    t = time.time()
    f = ifcopenshell.open(a.ifc)
    stats["parse_sec"] = round(time.time() - t, 2)
    stats["schema"] = f.schema
    # metres per file length unit (handles IfcSIUnit prefixes AND
    # IfcConversionBasedUnit i.e. feet / inches) -> we emit millimetres
    try:
        m_per_unit = float(ifcopenshell.util.unit.calculate_unit_scale(f))
    except Exception:
        m_per_unit = 1.0
    stats["m_per_ifc_unit"] = m_per_unit
    stats["file_length_unit"] = length_unit_name(f)

    fh = open(a.out, "w", buffering=1 << 20)
    w = StepWriter(fh, os.path.basename(a.ifc), ".MILLI.", 0.01)
    w.sc = m_per_unit * 1000.0
    w.nodedup = a.nodedup
    w.noplane = a.noplane
    w.prec = a.prec
    w.split_lumps = not a.nodedup and os.environ.get("IFC2STEP_NO_LUMP_SPLIT", "") != "1"

    skipped = None
    if a.mode in ("transcode", "hybrid"):
        skipped = run_transcode(f, w, stats)
    if a.mode == "tess":
        run_tess(a.ifc, w, stats, None, a.threads)
    elif a.mode == "hybrid" and skipped:
        run_tess(a.ifc, w, stats, skipped, a.threads)

    w.close()
    fh.close()
    stats["out_bytes"] = os.path.getsize(a.out)
    stats["parts"] = w.n_parts
    stats["faces"] = w.n_faces
    stats["points"] = w.n_pts
    stats["dirs"] = w.n_dirs
    stats["entities"] = w.n - 100
    stats["total_sec"] = round(time.time() - T0, 2)
    stats["peak_rss_mb"] = rss()
    stats["bbox"] = [round(v, 3) for v in w.bb]
    stats["degenerate_faces_dropped"] = getattr(w, "n_degenerate", 0)
    stats["lump_split"] = dict(w.lump_stats, enabled=w.split_lumps)
    stats["bytes_per_face"] = round(stats["out_bytes"] / max(1, w.n_faces), 1)
    stats["expansion"] = round(stats["out_bytes"] / max(1, stats["in_bytes"]), 2)
    if a.gzip:
        t = time.time()
        os.system("gzip -1 -k -f '%s'" % a.out)
        stats["gz_sec"] = round(time.time() - t, 2)
        stats["gz_bytes"] = os.path.getsize(a.out + ".gz")
        stats["gz_ratio"] = round(stats["out_bytes"] / max(1, stats["gz_bytes"]), 1)
        os.remove(a.out + ".gz")
    with open(a.out + ".stats.json", "w") as sf:
        json.dump(stats, sf, indent=1)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
