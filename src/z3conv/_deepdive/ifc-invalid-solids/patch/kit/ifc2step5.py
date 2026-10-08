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
import sys, os, json, time, math, argparse, datetime, collections
import re as _re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shellfix


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
    # compact STEP REAL: must contain '.'. 15 significant digits: points are already rounded to --prec decimals, so
    # this prints exactly those digits; '%.9g' cut georeferenced coordinates (state-plane feet -> 3e9 mm) to a 10 mm
    # grid and folded small faces into self-intersecting loops (z3 shellfix README, model 1481043e)
    if v == 0.0:
        return "0."
    s = "%.15g" % v
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
        self.shellfix = True                   # repair closed shells before writing (shellfix.repair_shell)
        self.repair = collections.Counter()    # what the repair did, for <out>.stats.json
        self.pending_open = []                 # OPEN_SHELLs of the current product (pieces that are not closed)
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
        self.pending_open = []

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

    def face_spec(self, loops):
        """loops: list of (point_id_list, pts, is_outer) -> cleaned [(pids, pts, is_outer)], outer loop first, or None.
        z4 fix: repeated points (zero-length edges, e.g. after 0.01 mm rounding) and loops that enclose no area are
        dropped; OpenCASCADE 8.0.1 segfaults transferring such faces. Geometry is unchanged."""
        out = []
        for pids, pts, outer in loops:
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
            if outer and not any(o for _, _, o in out):
                out.insert(0, (cp, cq, True))
            else:
                out.append((cp, cq, outer))
        return out or None

    def emit_face(self, spec):
        """cleaned loops (face_spec) -> FACE_SURFACE id or None"""
        bounds = []
        normal = None
        for pids, pts, outer in spec:
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
            return f
        if normal is None:
            return None
        nx, ny, nz, org = normal
        pl = self.plane_from_normal(nx, ny, nz, self.pt(*org))
        f = self.e("FACE_SURFACE('',(%s),#%d,.T.)"
                   % (",".join("#%d" % b for b in bounds), pl))
        self.n_faces += 1
        return f

    def face(self, loops):
        """loops: list of (point_id_list, pts, is_outer). Returns face id or None."""
        spec = self.face_spec(loops)
        return self.emit_face(spec) if spec else None

    def closed_breps(self, specs):
        """faces (face_spec results) of ONE closed shell -> list of FACETED_BREP ids. shellfix.repair_shell first
        (inner loops against the outer loop, double-sided meshes collapsed, internal walls removed, T-junctions split,
        tiny gaps closed, faces re-oriented consistently and outward, one brep per closed piece); vertices are never
        moved. A piece that is still not a closed 2-manifold (open source surface: DWF-import meshes, zero-thickness
        faces) is written as an OPEN_SHELL surface (self.pending_open, picked up by part()) instead of a FACETED_BREP
        that OpenCASCADE reads as an invalid solid. Closed shells that need no repair are written exactly as before."""
        specs = [sp for sp in specs if sp]
        if not specs:
            return []
        if not self.shellfix or self.nodedup:      # --nodedup: no shared vertex ids, no topology to repair
            r = self.solid([f for f in (self.emit_face(sp) for sp in specs) if f], True)
            return [r[0]] if r else []
        Psrc = {}
        for sp in specs:
            for pids, pts, outer in sp:
                Psrc.update(zip(pids, pts))
        sc, d = self.sc, self.prec
        # millimetres, rounded exactly as pt() writes them: the repair sees the coordinates OpenCASCADE will read
        P = {p: (round(q[0] * sc, d), round(q[1] * sc, d), round(q[2] * sc, d)) for p, q in Psrc.items()}
        faces = [[list(pids) for pids, pts, outer in sp] for sp in specs]
        try:
            pieces, info = shellfix.repair_shell(faces, P)
        except Exception as e:                      # never lose a part to the repair
            self.repair['repair_error'] += 1
            sys.stderr.write("[shellfix] %s: %s\n" % (type(e).__name__, e))
            r = self.solid([f for f in (self.emit_face(sp) for sp in specs) if f], True)
            return [r[0]] if r else []
        if info:
            self.repair.update(info); self.repair['breps_repaired'] += 1
        out = []
        for pc in pieces:
            closed = shellfix.piece_closed(faces, pc)
            fids = []
            for fi, rev in pc:
                if not rev and fi < len(specs) and faces[fi] == [list(x[0]) for x in specs[fi]]:
                    f = self.emit_face(specs[fi])
                else:
                    lps = [lp[::-1] for lp in faces[fi]] if rev else faces[fi]
                    f = self.emit_face([(lp, [Psrc[p] for p in lp], k == 0) for k, lp in enumerate(lps)])
                if f:
                    fids.append(f)
            if not fids:
                continue
            if closed:
                r = self.solid(fids, True)
                out.append(r[0])
            else:
                self.pending_open.append(self.solid(fids, False)[0])
                self.repair['open_pieces_as_surface'] += 1
        return out

    def solid(self, face_ids, closed=True):
        if not face_ids:
            return None
        sh = self.e("%s('',(%s))" % ("CLOSED_SHELL" if closed else "OPEN_SHELL",
                                     ",".join("#%d" % f for f in face_ids)))
        if closed:
            return self.e("FACETED_BREP('',#%d)" % sh), True
        return sh, False

    def part(self, name, items, faceted=True, pid=None, desc=None):
        """items: list of brep ids (faceted) or open shell ids. pid = source part id (IFC GlobalId) written as
        PRODUCT.id and desc = source class written as PRODUCT.description (z3: exact part mapping for grading)."""
        opens, self.pending_open = self.pending_open, []
        if not items and not opens:
            return
        nm = step_str(name or "part")
        p = self.e("PRODUCT('%s','%s','%s',(#%d))" % (step_str(pid, 64) if pid else nm, nm, step_str(desc or "", 64), self.ctx_prod))
        self.e("PRODUCT_RELATED_PRODUCT_CATEGORY('part','',(#%d))" % p)
        pdf = self.e("PRODUCT_DEFINITION_FORMATION('','',#%d)" % p)
        pd = self.e("PRODUCT_DEFINITION('design','',#%d,#%d)" % (pdf, self.ctx_pdef))
        pds = self.e("PRODUCT_DEFINITION_SHAPE('','',#%d)" % pd)
        kind = ("FACETED_BREP_SHAPE_REPRESENTATION" if faceted
                else "SHELL_BASED_SURFACE_MODEL_SHAPE_REPRESENTATION")
        if not faceted or (opens and not items):
            sbsm = self.e("SHELL_BASED_SURFACE_MODEL('',(%s))"
                          % ",".join("#%d" % i for i in list(items) + opens))
            items = [sbsm]
            kind = "MANIFOLD_SURFACE_SHAPE_REPRESENTATION"
        elif opens:
            # closed pieces + an open remainder: FACETED_BREP_SHAPE_REPRESENTATION may hold faceted breps only
            items = list(items) + [self.e("SHELL_BASED_SURFACE_MODEL('',(%s))" % ",".join("#%d" % i for i in opens))]
            kind = "SHAPE_REPRESENTATION"
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


def shell_faces(shell, m, w, emit=True):
    """IfcConnectedFaceSet -> list of step face ids (emit=False: list of face specs for StepWriter.closed_breps)"""
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
        if not emit:
            sp = w.face_spec(loops)
            if sp:
                out.append(sp)
            continue
        fid = w.face(loops)
        if fid:
            out.append(fid)
    return out


def item_to_step(item, m, w):
    """Return (list_of_items, faceted_bool) or None if unsupported."""
    t = item.is_a()
    if t in ("IfcFacetedBrep", "IfcFacetedBrepWithVoids"):
        fl = shell_faces(item.Outer, m, w, emit=False)
        if fl is None:
            return None
        res = w.closed_breps(fl)
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
        closed = (item.Closed is True) if hasattr(item, "Closed") else True
        for poly in polys:
            ii = [p - 1 for p in poly]
            pts = [mat_apply(m, coords[k]) for k in ii]
            if closed:
                sp = w.face_spec([([pids[k] for k in ii], pts, True)])
                if sp:
                    faces.append(sp)
                continue
            fid = w.face([([pids[k] for k in ii], pts, True)])
            if fid:
                faces.append(fid)
        if not faces:
            return None
        if closed:
            brs = w.closed_breps(faces)
            return (brs, True) if (brs or w.pending_open) else None
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
        if not ok or not (outs or w.pending_open):
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
            sp = w.face_spec([([pids[a], pids[b], pids[c]], pts, True)])
            if sp:
                faces.append(sp)
        brs = w.closed_breps(faces) if faces else []
        if brs or w.pending_open:
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
    ap.add_argument("--no-shellfix", action="store_true", help="write closed shells as they come (pre-shellfix output)")
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
    w.shellfix = not a.no_shellfix

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
    stats["shellfix"] = (dict(w.repair) or {"breps_repaired": 0}) if w.shellfix else "off"
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
