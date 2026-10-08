"""ACIS SAB body (as parsed by acis.py) -> polygon faces in world metres.

Faces returned as dict(outer=[xyz...], holes=[[xyz...]...]) (planar) or triangles (curved faces, as 3-point outers).
Supported: plane-surface (exact; straight edges exact, ellipse edges sampled, intcurve edges chorded -> flagged),
cone-surface (cylinders/cones; triangulated in (theta, h) parameter space). spline/torus/sphere faces -> skipped (flagged).
"""
import math
import numpy as np
import acis  # noqa: F401  (patches ezdxf's SAB decoder)
import ezdxf.acis.sab as S

P, LOC, DIR, DBL, TRUE, FALSE = S.Tags.POINTER, S.Tags.LOCATION_VEC, S.Tags.DIRECTION_VEC, S.Tags.DOUBLE, S.Tags.BOOL_TRUE, S.Tags.BOOL_FALSE
SAG = 0.004      # m, max chord sagitta for sampled arcs
MINSEG = 12      # per full circle


def ptrs(e):
    return [t.value for t in e.data if t.tag == P]


def locs(e):
    return [np.array(t.value, float) for t in e.data if t.tag in (LOC, DIR)]


def dbls(e):
    return [t.value for t in e.data if t.tag == DBL]


def bools(e):
    return [t.tag == TRUE for t in e.data if t.tag in (TRUE, FALSE)]


def isnull(e):
    return e is None or getattr(e, 'name', 'null-ptr') in ('null-ptr', '') or getattr(e, 'id', 0) == -1 and e.name == 'null-ptr'


def nm(e):
    return getattr(e, 'name', '')


class Body:
    def __init__(self, sab):
        self.b = S.parse_sab(sab)
        self.flags = set()

    # ---------------------------------------------------------------- topology
    def faces(self):
        out = []
        for body in [e for e in self.b.entities if nm(e) == 'body']:
            bp = ptrs(body)                        # pattern, lump, wire, transform
            T = self.transform(bp[3] if len(bp) > 3 else None)
            lump = bp[1] if len(bp) > 1 else None
            guard = 0
            while lump is not None and nm(lump) == 'lump' and guard < 10000:
                lp = ptrs(lump)                    # pattern, next, shell, body
                shell = lp[2]
                while shell is not None and nm(shell) == 'shell':
                    sp = ptrs(shell)               # pattern, next, subshell, face, wire, lump
                    face = sp[3]
                    while face is not None and nm(face) == 'face':
                        out.append((face, T))
                        face = ptrs(face)[1]
                    shell = sp[1]
                lump = lp[1]; guard += 1
        return out

    def transform(self, t):
        if t is None or nm(t) != 'transform':
            return None
        vals = [x for x in dbls(t)]
        if len(vals) >= 12:
            M = np.array(vals[:12], float).reshape(4, 3)      # rows: x, y, z axes, translation (ACIS convention)
            if not np.allclose(M[:3], np.eye(3)) or np.linalg.norm(M[3]) > 0:
                self.flags.add('transform')
                return M
        return None

    def loops(self, face):
        out = []
        lp = ptrs(face)[2]
        g = 0
        while lp is not None and nm(lp) == 'loop' and g < 1000:
            out.append(lp)
            lp = ptrs(lp)[1]; g += 1
        return out

    def coedges(self, loop):
        first = ptrs(loop)[2]
        out, ce, g = [], first, 0
        while ce is not None and nm(ce) == 'coedge' and g < 100000:
            out.append(ce)
            ce = ptrs(ce)[1]; g += 1
            if ce is first:
                break
        return out

    @staticmethod
    def vpt(v):
        return np.array(locs(ptrs(v)[2])[0], float)

    # ---------------------------------------------------------------- curves
    def coedge_points(self, ce):
        """points from the coedge start (inclusive) to its end (exclusive)"""
        cp = ptrs(ce)                              # pattern, next, prev, partner, edge, loop, pcurve
        edge = cp[4]
        rev_ce = bools(ce)[0] if bools(ce) else False
        ep = ptrs(edge)                            # pattern, v0, v1, coedge, curve
        v0, v1, curve = ep[1], ep[2], ep[4]
        rev_e = bools(edge)[0] if bools(edge) else False
        a, b = (v1, v0) if rev_ce else (v0, v1)
        pa, pb = self.vpt(a), self.vpt(b)
        cn = nm(curve)
        if cn.startswith('straight') or curve is None or nm(curve) == 'null-ptr':
            return [pa]
        if cn.startswith('ellipse'):
            L = locs(curve)
            c, n, M = L[0], L[1], L[2]
            ratio = dbls(curve)[0] if dbls(curve) else 1.0
            n = n / np.linalg.norm(n); R = float(np.linalg.norm(M)); u = M / R; w = np.cross(n, u)
            d = (1 if not rev_e else -1) * (1 if not rev_ce else -1)

            def ang(p):
                q = p - c
                return math.atan2(float(q @ w) / max(ratio, 1e-9), float(q @ u))
            a0, a1 = ang(pa), ang(pb)
            if a is b or np.linalg.norm(pa - pb) < 1e-7:
                sweep = 2 * math.pi
            else:
                sweep = ((a1 - a0) * d) % (2 * math.pi)
                if sweep < 1e-9:
                    sweep = 2 * math.pi
            nseg = max(2, int(math.ceil(sweep / (2 * math.pi) * MINSEG)))
            if R > SAG:
                nseg = max(nseg, int(math.ceil(sweep / (2 * math.acos(max(-1.0, 1 - SAG / R))))))
            nseg = min(nseg, 720)
            return [c + u * R * math.cos(a0 + d * sweep * k / nseg) + w * R * ratio * math.sin(a0 + d * sweep * k / nseg) for k in range(nseg)]
        if cn.startswith('intcurve'):
            ed = dbls(edge)
            try:
                bs = parse_bspline(curve)
            except Exception:
                bs = None
            if bs is not None and len(ed) >= 2:
                t0, t1 = ed[0], ed[1]
                for (u0, u1) in ((t0, t1), (-t1, -t0)):
                    try:
                        q0, q1 = bs(u0), bs(u1)
                    except Exception:
                        continue
                    e0, e1 = (self.vpt(v0), self.vpt(v1))
                    if np.linalg.norm(q0 - e0) < 1e-3 and np.linalg.norm(q1 - e1) < 1e-3:
                        n_ = int(min(400, max(4, math.ceil(bs.length_est(u0, u1) / 0.05))))
                        pts = [bs(u0 + (u1 - u0) * k / n_) for k in range(n_)] + [q1]
                        if rev_ce:
                            pts = pts[::-1]
                        return pts[:-1]
                    if np.linalg.norm(q0 - e1) < 1e-3 and np.linalg.norm(q1 - e0) < 1e-3:
                        n_ = int(min(400, max(4, math.ceil(bs.length_est(u0, u1) / 0.05))))
                        pts = [bs(u1 + (u0 - u1) * k / n_) for k in range(n_)] + [q0]
                        if rev_ce:
                            pts = pts[::-1]
                        return pts[:-1]
        # other curve types / unresolvable spline: chord (flagged)
        self.flags.add('chorded_' + cn.split('-')[0])
        return [pa]

    def loop_points(self, loop):
        pts = []
        for ce in self.coedges(loop):
            pts += self.coedge_points(ce)
        # drop consecutive duplicates
        out = []
        for p in pts:
            if not out or np.linalg.norm(p - out[-1]) > 1e-7:
                out.append(p)
        if len(out) > 1 and np.linalg.norm(out[0] - out[-1]) < 1e-7:
            out.pop()
        return out

    # ---------------------------------------------------------------- faces
    def polygons(self):
        """-> (faces, complete) ; faces = list of (outer, holes) with numpy points (world metres)"""
        res = []; complete = True
        for face, T in self.faces():
            fp = ptrs(face)                        # pattern, next, loop, shell, subshell, surface
            surf = fp[5] if len(fp) > 5 else None
            sn = nm(surf)
            rev = bools(face)[0] if bools(face) else False
            try:
                if sn.startswith('plane'):
                    loops = [self.loop_points(l) for l in self.loops(face)]
                    loops = [l for l in loops if len(l) >= 3]
                    if not loops:
                        continue
                    nrm = locs(surf)[1] * (-1 if rev else 1)
                    # outer loop = largest area projected on the plane
                    areas = [abs(poly_area(l, nrm)) for l in loops]
                    k = int(np.argmax(areas))
                    res.append((loops[k], [l for i, l in enumerate(loops) if i != k]))
                elif sn.startswith('cone'):
                    tris = self.cone_triangles(face, surf, rev)
                    if tris is None:
                        tris = self.boundary_fill(face)
                        self.flags.add('cone_face_approx' if tris else 'cone_face_skipped')
                        complete = complete and bool(tris)
                    if tris:
                        res += [(t, []) for t in tris]
                else:
                    tris = self.boundary_fill(face)
                    tag = sn.split('-')[0] or 'unknown'
                    self.flags.add('%s_face_approx' % tag if tris else '%s_face_skipped' % tag)
                    if tris:
                        res += [(t, []) for t in tris]
                    else:
                        complete = False
            except Exception as e:
                complete = False; self.flags.add('face_error:%s' % type(e).__name__)
            if T is not None and res:
                pass
        if any(T is not None for _, T in self.faces()):
            T = [T for _, T in self.faces() if T is not None][0]
            R, t = T[:3], T[3]
            res = [([p @ R + t for p in o], [[p @ R + t for p in h] for h in hs]) for o, hs in res]
        return res, complete

    def boundary_fill(self, face):
        """approximate a curved face by ear-clipping its (sampled) outer boundary on the best-fit plane"""
        loops = [self.loop_points(l) for l in self.loops(face)]
        loops = [l for l in loops if len(l) >= 3]
        if len(loops) != 1:
            return None
        pts = loops[0]
        A = np.array(pts); c = A.mean(0)
        _, _, vt = np.linalg.svd(A - c)
        e1, e2 = vt[0], vt[1]
        tri = ear_clip([(float((p - c) @ e1), float((p - c) @ e2)) for p in pts])
        if tri is None:
            return None
        return [[pts[i] for i in t] for t in tri]

    def cone_triangles(self, face, surf, rev):
        L = locs(surf)
        c, ax, M = L[0], L[1] / np.linalg.norm(L[1]), L[2]
        R0 = float(np.linalg.norm(M)); u = M / R0; w = np.cross(ax, u)
        loops = [self.loop_points(l) for l in self.loops(face)]
        loops = [l for l in loops if len(l) >= 2]
        if not loops:
            return None

        def th(p):
            q = p - c
            return math.atan2(float(q @ w), float(q @ u)), float(q @ ax)
        # two closed loops around the axis (cylinder/cone wall, ends may be inclined): strip at common theta
        if len(loops) == 2:
            try:
                prof = []
                for l in loops:
                    t = np.array([th(p)[0] for p in l]); h = np.array([th(p)[1] for p in l])
                    r = np.array([np.linalg.norm((p - c) - ax * ((p - c) @ ax)) for p in l])
                    span = np.ptp(np.unwrap(np.append(t, t[0])))
                    if abs(abs(span) - 2 * math.pi) > 0.3 and np.ptp(t) < 5.5:
                        raise ValueError('loop does not go around the axis')
                    o = np.argsort(t)
                    prof.append((t[o], h[o], r[o]))
                n = max(24, max(len(l) for l in loops))
                ts = np.linspace(-math.pi, math.pi, n + 1)
                P = lambda t, h, r: c + ax * h + u * r * math.cos(t) + w * r * math.sin(t)
                H = [np.interp(ts, pt, ph, period=2 * math.pi) for pt, ph, pr in prof]
                Rr = [np.interp(ts, pt, pr, period=2 * math.pi) for pt, ph, pr in prof]
                tris = []
                for k in range(n):
                    a0, a1 = P(ts[k], H[0][k], Rr[0][k]), P(ts[k + 1], H[0][k + 1], Rr[0][k + 1])
                    b0, b1 = P(ts[k], H[1][k], Rr[1][k]), P(ts[k + 1], H[1][k + 1], Rr[1][k + 1])
                    tris += [[a0, a1, b1], [a0, b1, b0]]
                return tris
            except ValueError:
                pass
        if len(loops) == 2 and all(len(l) >= MINSEG for l in loops):
            A = [th(p) for p in loops[0]]; Bp = [th(p) for p in loops[1]]
            ha, hb = np.mean([h for _, h in A]), np.mean([h for _, h in Bp])
            if abs(np.ptp([h for _, h in A])) < 1e-6 and abs(np.ptp([h for _, h in Bp])) < 1e-6:
                n = max(len(A), len(Bp))
                ra = float(np.mean([np.linalg.norm((p - c) - ax * ((p - c) @ ax)) for p in loops[0]]))
                rb = float(np.mean([np.linalg.norm((p - c) - ax * ((p - c) @ ax)) for p in loops[1]]))
                tris = []
                for k in range(n):
                    t0 = 2 * math.pi * k / n; t1 = 2 * math.pi * (k + 1) / n
                    P = lambda t, h, r: c + ax * h + u * r * math.cos(t) + w * r * math.sin(t)
                    a0, a1, b0, b1 = P(t0, ha, ra), P(t1, ha, ra), P(t0, hb, rb), P(t1, hb, rb)
                    tris += [[a0, a1, b1], [a0, b1, b0]]
                return tris
        # general: single loop -> unwrap theta along the loop, ear-clip in (theta*r, h), map back
        if len(loops) == 1:
            pts = loops[0]
            uv = []; prev = None; off = 0.0
            for p in pts:
                t, h = th(p)
                if prev is not None:
                    while t + off - prev > math.pi:
                        off -= 2 * math.pi
                    while t + off - prev < -math.pi:
                        off += 2 * math.pi
                uv.append((t + off, h)); prev = t + off
            radii = [float(np.linalg.norm((p - c) - ax * ((p - c) @ ax))) for p in pts]
            rm = float(np.mean(radii)) or R0
            tri = ear_clip([(a * rm, h) for a, h in uv])
            if tri is None:
                return None
            return [[pts[i] for i in t] for t in tri]
        return None


class BSpline:
    def __init__(self, deg, knots, ctrl, w=None):
        self.p, self.U, self.P, self.w = deg, np.array(knots, float), np.array(ctrl, float), (np.array(w, float) if w is not None else None)

    def __call__(self, t):
        p, U = self.p, self.U
        t = min(max(t, U[p]), U[len(U) - p - 1])
        k = int(np.searchsorted(U, t, side='right') - 1)
        k = min(max(k, p), len(U) - p - 2)
        if self.w is None:
            d = [self.P[j + k - p].copy() for j in range(p + 1)]
        else:
            d = [np.append(self.P[j + k - p] * self.w[j + k - p], self.w[j + k - p]) for j in range(p + 1)]
        for r in range(1, p + 1):
            for j in range(p, r - 1, -1):
                den = U[j + 1 + k - r] - U[j + k - p]
                a = 0.0 if den == 0 else (t - U[j + k - p]) / den
                d[j] = (1 - a) * d[j - 1] + a * d[j]
        return d[p] if self.w is None else d[p][:3] / d[p][3]

    def length_est(self, u0, u1):
        ts = np.linspace(u0, u1, 17)
        q = [self(t) for t in ts]
        return float(sum(np.linalg.norm(q[i + 1] - q[i]) for i in range(16)))


def parse_bspline(curve):
    """first 'nubs'/'nurbs' block of an ACIS intcurve record -> BSpline (ACIS end-knot multiplicity = degree)"""
    toks = curve.data
    for i, t in enumerate(toks):
        if t.value in ('nubs', 'nurbs') and t.tag in (S.Tags.STR, S.Tags.ENTITY_TYPE):
            rational = t.value == 'nurbs'
            j = i + 1
            ints = []
            while len(ints) < 1:
                if toks[j].tag == S.Tags.INT:
                    ints.append(toks[j].value)
                j += 1
            deg = ints[0]
            while toks[j].tag != S.Tags.INT:       # skip closure enum
                j += 1
            nk = toks[j].value; j += 1
            knots = []
            for _ in range(nk):
                kv = toks[j].value; m = toks[j + 1].value; j += 2
                knots.append((kv, m))
            mults = [m for _, m in knots]
            mults[0] += 1; mults[-1] += 1
            U = [kv for (kv, _), m in zip(knots, mults) for _ in range(m)]
            nctrl = len(U) - deg - 1
            dim = 4 if rational else 3
            vals = []
            while len(vals) < nctrl * dim and j < len(toks):
                if toks[j].tag == S.Tags.DOUBLE:
                    vals.append(toks[j].value)
                elif toks[j].tag in (S.Tags.LOCATION_VEC, S.Tags.DIRECTION_VEC):
                    vals += list(toks[j].value)
                else:
                    break
                j += 1
            if len(vals) < nctrl * dim:
                return None
            A = np.array(vals[:nctrl * dim], float).reshape(nctrl, dim)
            return BSpline(deg, U, A[:, :3], A[:, 3] if rational else None)
    return None


def poly_area(pts, n):
    n = n / (np.linalg.norm(n) or 1)
    s = np.zeros(3)
    for i in range(len(pts)):
        s += np.cross(pts[i], pts[(i + 1) % len(pts)])
    return float(s @ n) / 2


def ear_clip(P):
    """simple polygon ear clipping; P = list of (x, y). -> list of index triples or None"""
    n = len(P)
    if n < 3:
        return None
    idx = list(range(n))
    area = sum(P[i][0] * P[(i + 1) % n][1] - P[(i + 1) % n][0] * P[i][1] for i in range(n))
    if area < 0:
        idx.reverse()

    def inside(p, a, b, c):
        def s(p1, p2, p3):
            return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
        d1, d2, d3 = s(p, a, b), s(p, b, c), s(p, c, a)
        return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))
    out = []; guard = 0
    while len(idx) > 3 and guard < 10 * n * n:
        guard += 1
        m = len(idx); found = False
        for k in range(m):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % m]
            a, b, c = P[i0], P[i1], P[i2]
            if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) <= 1e-14:
                continue
            if any(inside(P[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            out.append((i0, i1, i2)); idx.pop(k); found = True
            break
        if not found:
            return None
    if len(idx) == 3:
        out.append(tuple(idx))
    return out


def body_faces(blob):
    """blob -> (faces, complete, flags)"""
    sab = acis.blob_to_sab(blob)
    B = Body(sab)
    faces, complete = B.polygons()
    return faces, complete, sorted(B.flags)
