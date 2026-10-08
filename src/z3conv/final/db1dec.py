"""Generic Xsteel/Tekla .db1 decoder (engines 6.x-9.x).

A .db1 (gzip) is a sequence of runs of fixed-stride records whose header is
[objid:4][ref:4][0x04][...]. The field layout moves between engine versions, so
it is DISCOVERED per file from self-validating signatures (or taken from a
version layout table and re-verified):

  point     : 3 real-world coordinate doubles, keyed by the record's int at +9
  csys      : two orthonormal unit vectors, keyed by the int right after them
  member    : origin xyz + length doubles; two int refs to points whose distance
              equals the length on most rows; an int ref to a csys; an int ref to
              the part_attr record
  part_attr : the profile. Tekla runs strtok(profile, "0123456789") on the in-memory
              buffer before saving, so the stored buffer is the profile with ONE byte
              (the first digit after the leading token) replaced by NUL; the parameter
              tail is also stored whole in a separate string record. The identity
                  original = head + tail[-(len(after)+1)] + after,  original.endswith(tail)
              is used both to FIND the two fields and to rebuild the exact name.

Member solid: from origin O, length L along +/-x of its csys (sense chosen toward
the far reference point), profile height along the csys y, width along x cross y.
Validated against Tekla-exported IFC (8.07: 1681/1683 members exact; 7.64: 3860
exact on geometry).
"""
import gzip, collections, math, re, warnings
import numpy as np
warnings.filterwarnings('ignore')

PLATE1_RE = re.compile(r'^(?:PL|BL|PLT|FL)\s*\d+(?:\.\d+)?$')
PROF_RE = re.compile(r'^[A-Z\[]{1,8}[0-9][0-9A-Z./*X "\'-]*$')


def inkeys(keys, v):
    """membership of v in a SORTED key array."""
    v = np.asarray(v)
    if not len(keys): return np.zeros(len(v), bool)
    i = np.searchsorted(keys, v)
    return keys[np.minimum(i, len(keys) - 1)] == v


def load(p):
    r = open(p, 'rb').read()
    if r[:2] != b'\x1f\x8b': return r
    try:
        return gzip.decompress(r)
    except EOFError:
        # truncated archive copy: keep every byte that did arrive (records are self-describing
        # and every table is validated, so a cut tail only loses the parts stored there)
        import zlib
        return zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(r)


def _outline_ok(U, V, Lk):
    """rows of u/v outline arrays that form a real outline: >= 3 vertices before the (0,0)
    terminator, extent along u (or first edge, 7.x) == member length, area > 1, and no
    repeated consecutive vertex (a wrong array size shifts v and repeats vertices)."""
    R, cap = U.shape
    with np.errstate(invalid='ignore', over='ignore'):
        Z = (np.abs(U) < 1e-3) & (np.abs(V) < 1e-3); Z[:, 0] = False
        n = np.where(Z.any(1), Z.argmax(1), cap)
        j = np.arange(cap)[None, :]; valid = j < n[:, None]
        fin = np.where(valid, np.isfinite(U) & np.isfinite(V), True).all(1)
        Uv = np.where(valid, U, np.nan); Vv = np.where(valid, V, np.nan)
        ext = np.nanmax(Uv, 1) - np.nanmin(Uv, 1)
        first = np.abs(U[:, 1] - Lk) < 0.05
        width = np.abs(ext - Lk) < 0.05
        Uz = np.where(valid, U, 0.0); Vz = np.where(valid, V, 0.0)
        cross = (Uz[:, :-1] * Vz[:, 1:] - Uz[:, 1:] * Vz[:, :-1])
        cross = np.where(j[:, :-1] < (n[:, None] - 1), cross, 0.0).sum(1)
        last = np.clip(n - 1, 0, cap - 1); r = np.arange(R)
        cross += Uz[r, last] * Vz[:, 0] - Uz[:, 0] * Vz[r, last]
        area = 0.5 * np.abs(cross)
        du = np.abs(np.diff(U, axis=1)) < 1e-3; dv = np.abs(np.diff(V, axis=1)) < 1e-3
        dup = ((du & dv) & (j[:, :-1] < (n[:, None] - 1))).any(1)
        return fin & (n >= 3) & (first | width) & (area > 1.0) & ~dup


SENTINEL = 2147483647      # INT_MAX closes a contour's chamfer-type array


def _arc(C, A, B, ccw, tol=0.05):
    """points strictly between A and B on the circle about C (A, B on it), turning ccw or cw."""
    R = float(np.linalg.norm(A - C))
    a0 = math.atan2(A[1] - C[1], A[0] - C[0]); a1 = math.atan2(B[1] - C[1], B[0] - C[0])
    if ccw:
        while a1 <= a0: a1 += 2 * math.pi
    else:
        while a1 >= a0: a1 -= 2 * math.pi
    step = 2 * math.acos(max(-1.0, min(1.0, 1 - tol / R))) if R > tol else math.pi / 2
    k = int(min(180, max(2, math.ceil(abs(a1 - a0) / max(step, 1e-3)))))
    return [C + R * np.array([math.cos(t), math.sin(t)]) for t in np.linspace(a0, a1, k + 1)[1:-1]]


ARC_STATS = {"contours": 0, "arc_runs": 0, "refused_selfx": 0, "rounding_shrunk": 0, "changed": 0}   # per-process counters read by db1step


def _selfx(P):
    """True when the closed polygon P crosses itself (proper segment crossings)"""
    n = len(P)
    if n < 4: return False
    A = np.asarray(P)
    for i in range(n):
        p, q = A[i], A[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1: continue
            r, s = A[j], A[(j + 1) % n]
            d1 = (q[0]-p[0])*(r[1]-p[1]) - (q[1]-p[1])*(r[0]-p[0]); d2 = (q[0]-p[0])*(s[1]-p[1]) - (q[1]-p[1])*(s[0]-p[0])
            if d1 * d2 >= 0: continue
            d3 = (s[0]-r[0])*(p[1]-r[1]) - (s[1]-r[1])*(p[0]-r[0]); d4 = (s[0]-r[0])*(q[1]-r[1]) - (s[1]-r[1])*(q[0]-r[0])
            if d3 * d4 < 0: return True
    return False


REPAIR_OK = [False]      # cut-not-applied P14: set by Db.polygon for cut parts only (contour plates keep the refusal)
LAST_REPAIR = [None]     # cut-not-applied P14: (dropped sliver area mm2, outline area mm2) of the last repaired outline


def _selfx_pair(P):
    """first pair of properly crossing edges (i, j) of the closed polygon P, or None"""
    n = len(P); A = np.asarray(P)
    for i in range(n):
        p, q = A[i], A[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1: continue
            r, s = A[j], A[(j + 1) % n]
            d1 = (q[0]-p[0])*(r[1]-p[1]) - (q[1]-p[1])*(r[0]-p[0]); d2 = (q[0]-p[0])*(s[1]-p[1]) - (q[1]-p[1])*(s[0]-p[0])
            if d1 * d2 >= 0: continue
            d3 = (s[0]-r[0])*(p[1]-r[1]) - (s[1]-r[1])*(p[0]-r[0]); d4 = (s[0]-r[0])*(q[1]-r[1]) - (s[1]-r[1])*(q[0]-r[0])
            if d3 * d4 < 0: return i, j
    return None


def _area2(Q):
    return sum(Q[i][0] * Q[(i + 1) % len(Q)][1] - Q[(i + 1) % len(Q)][0] * Q[i][1] for i in range(len(Q))) / 2.0


def _repair_slivers(res, protect, tol=0.25):
    """cut-not-applied P14: an arc through a contour's arc point (type 40) can poke a hair across the neighbouring straight edges
    (a944 HRH_MASTER 7.64: 68 'BL25' cutters, the arc A-B-C rises 0.11 mm above edge D-A and dips 0.1 mm under C-D) -> the outline
    crosses itself and the cut was refused. At each crossing the outline is split into its two loops and the thin one is dropped,
    only while every dropped loop is a sliver (width = 2 x area / its longest edge <= tol mm, area <= 1 % of the outline).
    -> (outline, total dropped area mm2) or (None, None)"""
    Q = [(float(q[0]), float(q[1])) for q in res]; A0 = abs(_area2(Q)); dropped = 0.0
    for _ in range(32):
        pr = _selfx_pair(Q)
        if pr is None: return Q, dropped
        i, j = pr; n = len(Q)
        p, q, r, s_ = (np.array(Q[k % n]) for k in (i, i + 1, j, j + 1))
        d = q - p; e = s_ - r; den = d[0] * e[1] - d[1] * e[0]
        if abs(den) < 1e-15: return None, None
        t = ((r[0] - p[0]) * e[1] - (r[1] - p[1]) * e[0]) / den; X = (float(p[0] + t * d[0]), float(p[1] + t * d[1]))
        L1 = [X] + Q[i + 1:j + 1]; L2 = [X] + Q[j + 1:] + Q[:i + 1]
        a1, a2 = abs(_area2(L1)), abs(_area2(L2))
        keep, drop, ad = (L1, L2, a2) if a1 >= a2 else (L2, L1, a1)
        lmax = max(float(np.hypot(drop[k][0] - drop[k - 1][0], drop[k][1] - drop[k - 1][1])) for k in range(len(drop)))
        if ad > 0.01 * A0 or (lmax > 0 and 2.0 * ad / lmax > tol) or len(keep) < 3: return None, None
        dropped += ad; Q = keep
    return None, None


def _circ(a, b, c):
    """centre of the circle through a, b, c (None when collinear)"""
    ax, ay = a; bx, by = b; qx, qy = c
    dd = 2 * (ax * (by - qy) + bx * (qy - ay) + qx * (ay - by))
    if abs(dd) < 1e-9: return None
    ux = ((ax * ax + ay * ay) * (by - qy) + (bx * bx + by * by) * (qy - ay) + (qx * qx + qy * qy) * (ay - by)) / dd
    uy = ((ax * ax + ay * ay) * (qx - bx) + (bx * bx + by * by) * (ax - qx) + (qx * qx + qy * qy) * (bx - ax)) / dd
    return np.array([ux, uy])


def _apply_chamfers_v1(V):
    """PREVIOUS implementation (kept only to measure which contours the fix changes). Tekla contour points [(u, v, type, x, y)] -> outline [(u, v)].
    type 10 line (cut x/y along the edges), 20 rounding (tangent arc, radius x),
    40 arc point (the edge becomes the arc through the previous, this and the next point).
    Unknown types keep the sharp corner (counted by the caller)."""
    n = len(V); P = [np.array(v[:2], float) for v in V]; out = []
    for i in range(n):
        t, cx, cy = V[i][2], V[i][3], V[i][4]
        p, pp, pn = P[i], P[i - 1], P[(i + 1) % n]
        e1 = pp - p; e2 = pn - p; l1 = float(np.linalg.norm(e1)); l2 = float(np.linalg.norm(e2))
        if t == 0 or l1 < 1e-6 or l2 < 1e-6:
            out.append(p); continue
        e1 = e1 / l1; e2 = e2 / l2
        if t == 10 and cx > 0:
            d1 = cx; d2 = cy if cy > 0 else cx
            if d1 < l1 - 1e-6 and d2 < l2 - 1e-6: out += [p + e1 * d1, p + e2 * d2]
            else: out.append(p)
        elif t == 20 and cx > 0:
            th = math.acos(max(-1.0, min(1.0, float(e1 @ e2))))
            if th < 1e-3 or th > math.pi - 1e-3: out.append(p); continue
            d = cx / math.tan(th / 2)
            if d >= l1 - 1e-6 or d >= l2 - 1e-6: out.append(p); continue
            T1, T2 = p + e1 * d, p + e2 * d
            b = (e1 + e2) / np.linalg.norm(e1 + e2); C = p + b * cx / math.sin(th / 2)
            ccw = float(np.cross(T1 - C, T2 - C)) > 0
            out += [T1] + _arc(C, T1, T2, ccw) + [T2]
        elif t == 40:
            # circle through pp, p, pn; walk pp -> p -> pn
            ax, ay = pp; bx, by = p; qx, qy = pn
            dd = 2 * (ax * (by - qy) + bx * (qy - ay) + qx * (ay - by))
            if abs(dd) < 1e-9: out.append(p); continue
            ux = ((ax * ax + ay * ay) * (by - qy) + (bx * bx + by * by) * (qy - ay) + (qx * qx + qy * qy) * (ay - by)) / dd
            uy = ((ax * ax + ay * ay) * (qx - bx) + (bx * bx + by * by) * (ax - qx) + (qx * qx + qy * qy) * (bx - ax)) / dd
            # the triangle's winding is the travel direction pp -> p -> pn on the circle
            C = np.array([ux, uy]); ccw = float(np.cross(p - pp, pn - p)) > 0
            out += _arc(C, pp, p, ccw) + [p] + _arc(C, p, pn, ccw)
        else:
            out.append(p)
    clean = []
    for q in out:
        if not clean or np.linalg.norm(clean[-1] - q) > 1e-4: clean.append(q)
    if len(clean) > 1 and np.linalg.norm(clean[0] - clean[-1]) <= 1e-4: clean.pop()
    return [(float(q[0]), float(q[1])) for q in clean]


def apply_chamfers(V):
    """Current outline + count of contours whose outline differs from the previous implementation."""
    res = _apply_chamfers_v2(V)
    try:
        prev = _apply_chamfers_v1(V)
        same = res is not None and len(prev) == len(res) and all(abs(a[0] - b[0]) <= 1e-6 and abs(a[1] - b[1]) <= 1e-6 for a, b in zip(prev, res))
    except Exception:
        same = False
    if not same: ARC_STATS["changed"] += 1
    return res


def _apply_chamfers_v2(V):
    """Tekla contour points [(u, v, type, x, y)] -> outline [(u, v)].
    type 10 line (cut x/y along the edges), 20 rounding (tangent arc, radius x),
    40 arc point: the point lies on an arc through its neighbours. Built edge by edge so every edge is
    emitted exactly once: an edge touching an arc point becomes the arc of the circle through that arc
    point and its two neighbours (a run of arc points traces one arc; a contour made only of arc points,
    as Tekla users draw round plates, becomes the circle through its points).
    Unknown types keep the sharp corner. An outline that the treatment would make cross itself is refused
    (returns None, the plate is skipped and counted); a contour stored crossing itself is kept as stored."""
    n = len(V); P = [np.array(v[:2], float) for v in V]; T = [V[i][2] for i in range(n)]
    ARC_STATS["contours"] += 1
    if any(T[i] == 40 and T[(i + 1) % n] == 40 for i in range(n)): ARC_STATS["arc_runs"] += 1
    # corner treatments that replace the vertex itself (types 10 / 20); arc points stay as vertices.
    # Roundings: tangent length d = r / tan(theta/2) on both edges. When the two roundings that share an
    # edge (or one rounding alone) need more than that edge, both are shrunk in proportion so their
    # tangent points meet on it (Tekla draws e.g. radius-63.5 roundings at both ends of a 127 mm edge).
    corner = {}; rnd = {}; L = [float(np.linalg.norm(P[(i + 1) % n] - P[i])) for i in range(n)]
    for i in range(n):
        t, cx = V[i][2], V[i][3]
        if t != 20 or cx <= 0: continue
        e1 = P[i - 1] - P[i]; e2 = P[(i + 1) % n] - P[i]; l1 = float(np.linalg.norm(e1)); l2 = float(np.linalg.norm(e2))
        if l1 < 1e-6 or l2 < 1e-6: continue
        e1 = e1 / l1; e2 = e2 / l2; th = math.acos(max(-1.0, min(1.0, float(e1 @ e2))))
        if th < 1e-3 or th > math.pi - 1e-3: continue
        rnd[i] = [th, cx / math.tan(th / 2), e1, e2]
    scale = {i: 1.0 for i in rnd}
    for i in range(n):                                      # edge i -> i+1
        j = (i + 1) % n; need = (rnd[i][1] if i in rnd else 0.0) + (rnd[j][1] if j in rnd else 0.0)
        if need > L[i] * 0.999 and need > 0:
            f = L[i] * 0.999 / need
            for k in (i, j):
                if k in rnd: scale[k] = min(scale[k], f)
    for i in range(n):
        t, cx, cy = V[i][2], V[i][3], V[i][4]
        p, pp, pn = P[i], P[i - 1], P[(i + 1) % n]
        e1 = pp - p; e2 = pn - p; l1 = float(np.linalg.norm(e1)); l2 = float(np.linalg.norm(e2))
        if t in (0, 40) or l1 < 1e-6 or l2 < 1e-6: continue
        e1 = e1 / l1; e2 = e2 / l2
        if t == 10 and cx > 0:
            d1 = cx; d2 = cy if cy > 0 else cx
            if d1 < l1 - 1e-6 and d2 < l2 - 1e-6: corner[i] = [p + e1 * d1, p + e2 * d2]
        elif t == 20 and i in rnd:
            th, d0 = rnd[i][0], rnd[i][1]; d = d0 * scale[i]; r = d * math.tan(th / 2)
            if d < 1e-6: continue
            T1, T2 = p + e1 * d, p + e2 * d
            bis = (e1 + e2) / np.linalg.norm(e1 + e2); C = p + bis * r / math.sin(th / 2)
            ccw = float(np.cross(T1 - C, T2 - C)) > 0
            corner[i] = [T1] + _arc(C, T1, T2, ccw) + [T2]
            if scale[i] < 1.0: ARC_STATS["rounding_shrunk"] = ARC_STATS.get("rounding_shrunk", 0) + 1
    out = []
    for i in range(n):
        j = (i + 1) % n
        out += corner.get(i, [P[i]])
        if T[i] != 40 and T[j] != 40: continue
        k = i if T[i] == 40 else j                         # the arc point that owns this edge
        C = _circ(P[k - 1], P[k], P[(k + 1) % n])
        if C is None: continue                             # collinear: straight edge
        ccw = float(np.cross(P[k] - P[k - 1], P[(k + 1) % n] - P[k])) > 0
        a = corner[i][-1] if i in corner else P[i]; b = corner[j][0] if j in corner else P[j]
        out += _arc(C, a, b, ccw)
    clean = []
    for q in out:
        if not clean or np.linalg.norm(clean[-1] - q) > 1e-4: clean.append(q)
    if len(clean) > 1 and np.linalg.norm(clean[0] - clean[-1]) <= 1e-4: clean.pop()
    res = [(float(q[0]), float(q[1])) for q in clean]
    # refuse only a crossing that the corner/arc treatment itself created; a contour that Tekla stored
    # already crossing itself (e.g. a closing point a hair past the first point) is passed through as stored
    if (len(corner) or any(t == 40 for t in T)) and _selfx(res) and not _selfx([(float(p[0]), float(p[1])) for p in P]):
        if REPAIR_OK[0]:                                   # cut-not-applied P14: cut parts only
            rep, dev = _repair_slivers(res, {(float(p[0]), float(p[1])) for p in P})
            if rep is not None:
                ARC_STATS["selfx_repaired"] = ARC_STATS.get("selfx_repaired", 0) + 1; LAST_REPAIR[0] = (dev, abs(_area2(rep)))
                return rep
        ARC_STATS["refused_selfx"] += 1
        return None
    return res


class Db:
    _A4 = np.arange(4); _A8 = np.arange(8)

    def __init__(self, data):
        self.b = data
        self.L = len(data)
        self.u8 = np.frombuffer(data, np.uint8)

    # ------------------------------------------------------------ raw readers
    def I(self, o):
        o = np.asarray(o, np.int64).reshape(-1)
        ok = (o >= 0) & (o + 4 <= self.L)
        out = np.zeros(o.shape, np.int64)
        if ok.any():
            out[ok] = self.u8[o[ok, None] + self._A4].copy().view('<i4')[:, 0]
        return out

    def D(self, o):
        o = np.asarray(o, np.int64).reshape(-1)
        ok = (o >= 0) & (o + 8 <= self.L)
        out = np.full(o.shape, np.nan)
        if ok.any():
            out[ok] = self.u8[o[ok, None] + self._A8].copy().view('<f8')[:, 0]
        return out

    def F(self, o):
        o = np.asarray(o, np.int64).reshape(-1)
        ok = (o >= 0) & (o + 4 <= self.L)
        out = np.full(o.shape, np.nan)
        if ok.any():
            out[ok] = self.u8[o[ok, None] + self._A4].copy().view('<f4')[:, 0]
        return out

    def cstr(self, o, n=64):
        if o < 0: return ''
        e = self.b.find(b'\0', o, o + n)
        return self.b[o:e if e >= 0 else o + n].decode('latin1')

    # ------------------------------------------------------------ tables
    SEG_FLAGS = (4,)        # v2 (eng): record-header flag bytes taken as run starts (variant retry: 1, 4, 5)
    CSYS_SPREAD = False     # v2 (eng): judge a known csys table on a spread sample (variant retry only)

    def segment(self, maxstride=1500):
        u8 = self.u8; L = self.L
        cand = np.nonzero(u8[8:] == 4)[0] if tuple(self.SEG_FLAGS) == (4,) else np.nonzero(np.isin(u8[8:], np.array(self.SEG_FLAGS, np.uint8)))[0]
        cand = cand[cand + 13 < L]
        a = self.I(cand); r = self.I(cand + 4)
        cand = cand[(a > 0) & (r > 0)]   # object ids grow past 4e8 in long-lived models; any positive int32
        isH = np.zeros(L + 3 * maxstride + 16, bool); isH[cand] = True
        stride = np.zeros(len(cand), np.int32); todo = np.ones(len(cand), bool)
        for s in range(13, maxstride):
            c = cand[todo]
            if not len(c): break
            m = isH[c + s] & isH[c + 2 * s] & isH[c + 3 * s]
            idx = np.nonzero(todo)[0][m]; stride[idx] = s; todo[idx] = False
        order = {int(o): i for i, o in enumerate(cand)}
        used = np.zeros(len(cand), bool); runs = []
        for i in range(len(cand)):
            if used[i] or stride[i] == 0: continue
            s = int(stride[i]); p = int(cand[i]); recs = [p]
            while isH[p + s]:
                p += s; j = order.get(p)
                if j is not None: used[j] = True
                recs.append(p)
            if len(recs) >= 3: runs.append((s, np.array(recs, np.int64)))
        self.runs = runs
        bys = collections.defaultdict(list)
        for s, recs in runs: bys[s].append(recs)
        self.bystride = {s: np.unique(np.concatenate(v)) for s, v in bys.items()}
        self.seqidx = {}
        allk, allo, alls = [], [], []
        for s, recs in self.bystride.items():
            q = self.I(recs + 9); o = np.argsort(q, kind='stable')
            self.seqidx[s] = (q[o], recs[o])
            allk.append(q); allo.append(recs); alls.append(np.full(len(recs), s))
        if allk:
            k = np.concatenate(allk); o = np.concatenate(allo); st = np.concatenate(alls)
            srt = np.argsort(k, kind='stable')
            self.gkeys, self.goffs, self.gstr = k[srt], o[srt], st[srt]
        else:
            self.gkeys = self.goffs = self.gstr = np.zeros(0, np.int64)
        return runs

    def lookup(self, keys, stride=None):
        """key (int at +9) -> record offset, -1 if none (restricted to one stride if given)."""
        keys = np.asarray(keys, np.int64).reshape(-1)
        if stride is None:
            K, O = self.gkeys, self.goffs
        else:
            K, O = self.seqidx.get(stride, (np.zeros(0, np.int64), np.zeros(0, np.int64)))
        if not len(K): return np.full(keys.shape, -1)
        i = np.searchsorted(K, keys); i2 = np.minimum(i, len(K) - 1)
        return np.where(K[i2] == keys, O[i2], -1)

    def lookup_all(self, key, stride=None):
        K, O = (self.gkeys, self.goffs) if stride is None else self.seqidx.get(stride, (np.zeros(0, np.int64), np.zeros(0, np.int64)))
        if not len(K): return []
        lo, hi = np.searchsorted(K, key, 'left'), np.searchsorted(K, key, 'right')
        return [int(x) for x in O[lo:hi]]

    def lookup_raw(self, key):
        """records outside any detected run: find [objid][ref][0x04][key] directly."""
        pat = b'\x04' + int(key).to_bytes(4, 'little', signed=True); out = []; p = self.b.find(pat, 8)
        while p >= 0 and len(out) < 8:
            o = p - 8
            if int(self.I([o])[0]) > 0 and int(self.I([o + 4])[0]) > 0: out.append(o)
            p = self.b.find(pat, p + 1)
        return out

    FLAGS = (1, 4, 5)

    def flagged(self, keys):
        """records outside the fixed-stride runs, found by key whatever their header flag byte:
        8.65 keeps some part-attribute records (flag 0x01) and profile-name strings (0x05)
        there. Batched over the whole file -> {key: [record starts]} (cached)."""
        if not hasattr(self, '_flagged'): self._flagged = {}
        K = np.unique(np.array([int(k) for k in keys if int(k) > 0 and int(k) not in self._flagged], np.int64))
        if len(K):
            found = collections.defaultdict(list); u8 = self.u8
            for a in range(4):
                n = (self.L - a) // 4
                for c0 in range(0, n, 16_000_000):
                    v = np.frombuffer(self.b, '<i4', count=min(16_000_000, n - c0), offset=a + 4 * c0)
                    i = np.searchsorted(K, v); i[i >= len(K)] = 0
                    for j in np.nonzero(K[i] == v)[0]:
                        p = a + 4 * (c0 + int(j)); st = p - 9
                        if st < 0 or int(u8[p - 1]) not in self.FLAGS: continue
                        if int(self.I([st])[0]) > 0 and int(self.I([st + 4])[0]) > 0: found[int(v[j])].append(st)
            for k in K: self._flagged[int(k)] = found.get(int(k), [])
        return {int(k): self._flagged.get(int(k), []) for k in keys}

    def attr_records(self, lay, pa_seq):
        """part-attribute records for a key: the attribute table, any table, then flagged records"""
        pa = int(pa_seq)
        c = self.lookup_all(pa, lay['attr_stride'])
        if not c: c = self.lookup_all(pa)
        if not c: c = self.flagged([pa])[pa]
        return c

    def prefetch_attr(self, lay, keys):
        """resolve, in two batched passes, attribute records and their name-tail records that
        live outside the runs (so profile() never scans the file per key)."""
        keys = [int(k) for k in set(int(k) for k in keys) if k > 0]
        miss = [k for k in keys if not self.lookup_all(k, lay['attr_stride']) and not self.lookup_all(k)]
        if miss: self.flagged(miss)
        refs = set()
        for k in keys:
            for o in self.attr_records(lay, k):
                r = int(self.I([o + lay['rest_ref']])[0])
                if r > 0 and not self.lookup_all(r): refs.add(r)
        if refs: self.flagged(list(refs))

    def lookup_stride(self, keys):
        keys = np.asarray(keys, np.int64).reshape(-1)
        if not len(self.gkeys): return np.full(keys.shape, -1)
        i = np.searchsorted(self.gkeys, keys); i2 = np.minimum(i, len(self.gkeys) - 1)
        return np.where(self.gkeys[i2] == keys, self.gstr[i2], -1)

    # ------------------------------------------------------------ points
    # v2 (eng): coordinate bound. 1e8 mm (100 km) on the normal paths; decode() retries with GEO_MAX when
    # nothing decodes, for models placed at georeferenced (state-plane) coordinates: 8.85 'no_member_layout'
    # models with points at x 2.0e8, y 2.3e8 mm.
    PLAUS_MAX = 1e8
    GEO_MAX = 1e10

    def _plaus(self, v):
        return np.isfinite(v) & (np.abs(v) < self.PLAUS_MAX) & ((v == 0) | (np.abs(v) > 1e-30))

    @staticmethod
    def _nice(v):
        return (v == 0) | ((np.abs(v) >= 1e-2) & (np.abs(v) < 1e7))

    def _xyz(self, recs, k):
        x, y, z = self.D(recs + k), self.D(recs + k + 8), self.D(recs + k + 16)
        return x, y, z, self._plaus(x) & self._plaus(y) & self._plaus(z)

    def find_points(self, fixed=None):
        """Point layouts, tested run by run (different tables share strides) and
        unioned over runs passing with the same (stride, offset)."""
        grp = {}
        for s, recs in self.runs:
            if s < 37 or len(recs) < 3: continue
            if fixed:
                if s != fixed[0]: continue
                x, y, z, ok = self._xyz(recs[:64], fixed[1])
                if ok.mean() < 0.97: continue
                k = fixed[1]
            else:
                smp = recs[:64]; best = None
                for k in range(9, s - 23):
                    x, y, z, ok = self._xyz(smp, k)
                    if ok.mean() < 0.97: continue
                    if not ((np.abs(x) > 1e-3) | (np.abs(y) > 1e-3) | (np.abs(z) > 1e-3)).any(): continue
                    if (np.abs(x * x + y * y + z * z - 1) < 1e-6)[ok].mean() > 0.5: continue
                    sc = (self._nice(x) & self._nice(y) & self._nice(z)).mean()
                    if best is None or sc > best[0] + 1e-9: best = (sc, k)
                if not best or best[0] < 0.9: continue
                k = best[1]
            x, y, z, ok = self._xyz(recs, k)
            g = grp.setdefault((s, k), [[], []])
            g[0].append(self.I(recs[ok] + 9)); g[1].append(np.stack([x, y, z], 1)[ok])
        out = []
        for (s, k), (ks, xs) in grp.items():
            q = np.concatenate(ks); X = np.concatenate(xs); o = np.argsort(q, kind='stable')
            out.append(dict(stride=s, k=k, keys=q[o], xyz=X[o]))
        out.sort(key=lambda d: -len(d['keys']))
        return out

    # ------------------------------------------------------------ csys
    @staticmethod
    def _orthonormal(v1, v2):
        return ((np.abs((v1 * v1).sum(1) - 1) < 1e-6) & (np.abs((v2 * v2).sum(1) - 1) < 1e-6)
                & (np.abs((v1 * v2).sum(1)) < 1e-4))

    def find_csys(self, only=None):
        """Candidate orientation tables, kept SEPARATE: several tables hold orthonormal
        vector pairs and reuse the same key values. -> list of dict(stride, k, key, map, keys)."""
        grp = {}
        for s, recs in self.runs:
            if s < 57 or len(recs) < 3: continue
            if only and s != only[0]: continue
            smp = recs[:48]
            for k in ([only[1]] if only else range(9, s - 47)):
                v1 = np.stack([self.D(smp + k + 8 * i) for i in range(3)], 1)
                v2 = np.stack([self.D(smp + k + 24 + 8 * i) for i in range(3)], 1)
                if self._orthonormal(v1, v2).mean() < 0.5:   # unused slots hold zeros (7.64: 83% filled)
                    # v2 (eng): with a KNOWN table location (layout) a run may open with a block of other
                    # stride-61 records (8.85: 40+ non-orthogonal pairs, dot 0.0045, before the part csys);
                    # judge the table on an even sample of the whole run instead. Rows are still tested
                    # one by one below (strict), and full discovery (only=None) is unchanged.
                    if not only or not self.CSYS_SPREAD or len(recs) <= 48: continue
                    spr = recs[np.linspace(0, len(recs) - 1, 256).astype(np.int64)]
                    w1 = np.stack([self.D(spr + k + 8 * i) for i in range(3)], 1)
                    w2 = np.stack([self.D(spr + k + 24 + 8 * i) for i in range(3)], 1)
                    if self._orthonormal(w1, w2).mean() < 0.5: continue
                v1 = np.stack([self.D(recs + k + 8 * i) for i in range(3)], 1)
                v2 = np.stack([self.D(recs + k + 24 + 8 * i) for i in range(3)], 1)
                ok = self._orthonormal(v1, v2)
                after = self.I(recs + k + 48); sq = self.I(recs + 9)
                for name, keyv in (('after', after), ('seq', sq)):
                    m = grp.setdefault((s, k, name), {})
                    for i in np.nonzero(ok)[0]:
                        m.setdefault(int(keyv[i]), (v1[i], v2[i]))
                break
        return [dict(stride=s, k=k, key=n, map=m, keys=np.array(sorted(m), np.int64)) for (s, k, n), m in grp.items() if m]

    # ------------------------------------------------------------ members
    @staticmethod
    def _pt(P, keys):
        keys = np.asarray(keys)
        out = np.full((len(keys), 3), np.nan)
        if not len(P['keys']): return out
        i = np.searchsorted(P['keys'], keys); i2 = np.minimum(i, len(P['keys']) - 1)
        hit = P['keys'][i2] == keys
        out[hit] = P['xyz'][i2[hit]]
        return out

    def find_members(self, pts, cs):
        best = None
        runs = sorted([r for r in self.runs if r[0] >= 45 and len(r[1]) >= 3], key=lambda r: -len(r[1]))[:60]
        for s, recs in runs:
            fields = list(range(9, s - 3))
            smp = recs[:64]
            sints = {f: self.I(smp + f) for f in fields}
            ints = {}
            for pi, P in enumerate(pts[:6]):
                pf = []
                for f in fields:
                    if inkeys(P['keys'], sints[f]).mean() <= 0.7: continue
                    if f not in ints: ints[f] = self.I(recs + f)
                    if inkeys(P['keys'], ints[f]).mean() > 0.8: pf.append(f)
                if len(pf) < 2: continue
                for k in range(9, s - 31):
                    Ln = self.D(recs + k + 24)
                    if not ((np.isfinite(Ln) & (Ln > 0.5) & (Ln < 1e6)).mean() > 0.8): continue
                    for ia in range(len(pf)):
                        for ib in range(ia + 1, len(pf)):
                            fa, fb = pf[ia], pf[ib]
                            if abs(fa - fb) < 4 or k - 4 < fa < k + 32 or k - 4 < fb < k + 32: continue
                            d = np.linalg.norm(self._pt(P, ints[fa]) - self._pt(P, ints[fb]), axis=1)
                            sc = float(np.mean(np.abs(d - Ln) < 1.0))
                            if sc > 0.3 and (best is None or sc * len(recs) > best[0]):
                                best = (sc * len(recs), s, k, pi, fa, fb, sc, recs)
        if not best: return None
        _, s, k, pi, fa, fb, sc, recs = best
        cf = None; bestf = 0; bestsc = None
        P = pts[pi]; d = self._pt(P, self.I(recs + fb)) - self._pt(P, self.I(recs + fa))
        dn = np.linalg.norm(d, axis=1); dok = np.isfinite(dn) & (dn > 1)
        for ci, C in enumerate(cs):
            for f in range(9, s - 3):
                if (k - 4 < f < k + 32) or f in (fa, fb): continue
                keys = self.I(recs + f); fr = inkeys(C['keys'], keys).mean()
                if fr <= 0.5: continue
                sel = np.nonzero(dok & inkeys(C['keys'], keys))[0]
                if len(sel) < 10: continue
                X = np.array([C['map'][int(q)][0] for q in keys[sel]])
                ag = float(np.mean(np.abs((d[sel] / dn[sel, None] * X).sum(1)) > 0.999))
                csc = (round(ag, 2), fr)
                if ag >= 0.9 and (bestsc is None or csc > bestsc):
                    bestsc = csc; bestf = fr; cf = (f, ci)
        self._member_run = recs
        C = cs[cf[1]] if cf else None
        return dict(stride=s, xyz=k, pts_stride=pts[pi]['stride'], pts_k=pts[pi]['k'], pts=pi,
                    p1=fa, p2=fb, len_eq_pts=round(sc, 3),
                    csys=cf[0] if cf else None, csys_key=C['key'] if C else None,
                    csys_stride=C['stride'] if C else None, csys_k=C['k'] if C else None,
                    csys_frac=round(float(bestf), 3), n=int(len(recs)))

    # ------------------------------------------------------------ part_attr / profile
    def _buf(self, o, n=120):
        raw = self.b[o:o + n]
        e2 = raw.find(b'\0\0')
        return raw[:e2 if e2 >= 0 else n].decode('latin1')

    @staticmethod
    def rebuild(buf, tail):
        r = Db._rebuild(buf, tail)
        # profile names are printable text with at least one letter or digit
        if r is None or not all(32 <= ord(c) < 127 for c in r) or not any(c.isalnum() for c in r): return None
        return r

    @staticmethod
    def _rebuild(buf, tail):
        """buf: stored buffer (one byte strtok'd to NUL); tail: separately stored
        parameter string, which some engines TRUNCATE (~28 chars). Accept only if the
        tail agrees with the bytes after the NUL, then restore the lost byte."""
        n = buf.find('\0')
        if n < 0: return buf if buf else None
        head, after = buf[:n], buf[n + 1:].split('\0')[0]
        if not tail or (n == 0 and not after): return None
        if len(tail) > len(after) and tail.endswith(after):          # whole tail stored
            orig = head + tail[-(len(after) + 1)] + after
            if orig.endswith(tail): return orig
        if len(tail) >= 2 and after.startswith(tail[1:]) and len(tail) - 1 >= min(len(after), 8):
            return head + tail[0] + after                            # truncated tail
        return None

    def _strides_holding(self, vals, minfrac):
        """strides whose record keys (int at +9) cover >= minfrac of vals, best first."""
        out = []
        for S, (K, O) in self.seqidx.items():
            fr = inkeys(K, vals).mean() if len(vals) else 0
            if fr >= minfrac: out.append((fr, S))
        return [S for fr, S in sorted(out, reverse=True)]

    def find_attr(self, lay):
        recs = self._member_run; k0 = lay['xyz']
        skip = set(range(k0 - 3, k0 + 32)) | {lay['p1'], lay['p2'], lay['csys']}
        best = None
        for f in range(9, lay['stride'] - 3):
            if f in skip: continue
            vals = np.unique(self.I(recs + f))
            for S in self._strides_holding(vals, 0.5):
                if S < 60: continue
                pa = self.lookup(vals, S); pa = pa[pa >= 0]
                if len(pa) == 0: continue
                smp = pa[:200]; found = None
                for k in range(9, S - 3):
                    bufs = [self._buf(int(o) + k) for o in smp]
                    if np.mean([b.find('\0') > 0 for b in bufs]) < 0.3: continue
                    for g in range(9, S - 3):
                        if k <= g < k + 40: continue
                        refs = self.I(smp + g)
                        for T in self._strides_holding(np.unique(refs), 0.9)[:4] + [None]:
                            ro = self.lookup(refs, T)
                            if (ro >= 0).mean() < 0.9: continue
                            for q in range(9, min(T, 64) if T else 64):
                                tails = [self.cstr(int(r) + q, 160) for r in ro]
                                names = [self.rebuild(b, t) for b, t in zip(bufs, tails)]
                                good = np.mean([x is not None and len(x) >= 2 for x in names])
                                mang = np.mean([b.find('\0') > 0 and x is not None for b, x in zip(bufs, names)])
                                if good > 0.9 and mang > 0.3:
                                    found = (good, k, g, T, q); break
                            if found: break
                        if found: break
                    if found: break
                if found:
                    sc = found[0] * len(pa)
                    if best is None or sc > best[0]:
                        best = (sc, f, S) + found[1:] + (found[0],)
                    break
        if best:
            _, f, S, k, g, T, q, good = best
            lay.update(attr=f, attr_stride=S, prof_off=k, rest_ref=g, rest_stride=T, rest_off=q, prof_score=round(float(good), 3))
        return lay

    def profile(self, lay, pa_seq):
        # attribute table, else a second table of another width, else a flagged record (8.65)
        cands = self.attr_records(lay, pa_seq)
        for o in cands:
            buf = self._buf(o + lay['prof_off'])
            if buf.find('\0') < 0:
                # Some records keep ONLY the leading token ('W') and the whole parameter tail
                # ('410X38.8') lives in the linked string record -> 'W410X38.8'.
                if buf and len(buf) <= 8 and all(c.isalpha() or c in '[_' for c in buf):
                    ref = int(self.I([o + lay['rest_ref']])[0])
                    rc = (self.lookup_all(ref, lay.get('rest_stride')) if lay.get('rest_stride') else []) or self.lookup_all(ref)
                    for r in rc:
                        tail = self.cstr(r + lay['rest_off'], 160)
                        if tail and tail[0].isdigit() and all(32 <= ord(c) < 127 for c in tail):
                            return buf + tail
                r = self.rebuild(buf, '')
                if r: return r
                continue
            ref = int(self.I([o + lay['rest_ref']])[0])
            cands = (self.lookup_all(ref, lay.get('rest_stride')) if lay.get('rest_stride') else []) + self.lookup_all(ref)
            if not cands: cands = self.flagged([ref])[ref] if hasattr(self, '_flagged') and ref in self._flagged else self.lookup_raw(ref)
            for r in cands:
                name = self.rebuild(buf, self.cstr(r + lay['rest_off'], 160))
                if name: return name
        return None

    def is_cut(self, lay, pa_seq):
        """Tekla cut parts (part-cut tools) carry material ANTIMATERIAL; they are not steel."""
        for o in self.attr_records(lay, pa_seq):
            if b'ANTIMATERIAL' in self.b[o:o + lay['attr_stride']]: return True
        return False

    # Contour plates are member records whose profile is a single thickness (PL25.4 / BL12.7).
    # Their outline is a separate record of float32 arrays u[cap], v[cap] in the plate's own
    # frame: u along the first edge (u[1] == member length), v along the part csys y.
    # Validated 75/77 + 13/13 IfcPlate outlines exact (7.82).
    def find_polygons(self, lay, M):
        cp = [m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m.get('cut')]
        if len(cp) < 3: return lay
        cp = cp[:400]
        offs = np.array([m['off'] for m in cp]); Lm = np.array([m['L'] for m in cp])
        used = {lay['p1'], lay['p2'], lay['csys'], lay.get('attr')} | set(range(lay['xyz'] - 3, lay['xyz'] + 32))
        best = None; hop1 = []
        for f in range(9, lay['stride'] - 3):
            if f in used: continue
            vals = self.I(offs + f)
            for T in self._strides_holding(np.unique(vals), 0.8)[:4]:
                ro = self.lookup(vals, T); ok = ro >= 0
                if ok.mean() < 0.8: continue
                ro = ro[ok]; Lk = Lm[ok]
                r = self._uv_detect(ro, Lk, T)
                if r and (best is None or r[0] > best[0]):
                    best = (r[0], dict(poly_field=f, poly_stride=T, poly_ub=r[1], poly_vb=r[2], poly_cap=r[3]))
                # a per-part link (not one shared record) is a candidate first hop
                if not r and len(np.unique(ro)) >= 0.2 * len(ro): hop1.append((f, T, ro, Lk))
        if best is None:
            # 8.5x+: the part points at a small per-part link record whose field holds the
            # outline record key (8.53: part +29 -> stride-33 record +25 -> outline)
            for f, T, ro, Lk in hop1:
                for g in range(9, T - 3):
                    v2 = self.I(ro + g)
                    if np.mean(v2 > 0) < 0.8: continue
                    for T2 in self._strides_holding(np.unique(v2[v2 > 0]), 0.8)[:3]:
                        r2o = self.lookup(v2, T2); ok2 = r2o >= 0
                        if ok2.mean() < 0.8: continue
                        r2 = self._uv_detect(r2o[ok2], Lk[ok2], T2)
                        if r2 and (best is None or r2[0] > best[0]):
                            best = (r2[0], dict(poly_field=f, poly_stride=T, poly_field2=g, poly_stride2=T2,
                                                poly_ub=r2[1], poly_vb=r2[2], poly_cap=r2[3]))
        if best is None:
            # v2 (eng): 9.50 stores the outline arrays as float64 (u[10]@25, v[10]@105 in a stride-465 record behind the
            # same 2-hop link); chamfer x/y stay float32 and the type array follows them
            for f, T, ro, Lk in hop1:
                for g in range(9, T - 3):
                    v2 = self.I(ro + g)
                    if np.mean(v2 > 0) < 0.8: continue
                    for T2 in self._strides_holding(np.unique(v2[v2 > 0]), 0.8)[:3]:
                        r2o = self.lookup(v2, T2); ok2 = r2o >= 0
                        if ok2.mean() < 0.8: continue
                        r2 = self._uv_detect64(r2o[ok2], Lk[ok2], T2)
                        if r2 and (best is None or r2[0] > best[0]):
                            best = (r2[0], dict(poly_field=f, poly_stride=T, poly_field2=g, poly_stride2=T2,
                                                poly_ub=r2[1], poly_vb=r2[2], poly_cap=r2[3], poly_f64=True))
        if best:
            lay.update(best[1]); lay['poly_frac'] = round(best[0], 3)
            self._detect_chamfers(lay, cp)
        return lay

    def _uv_detect64(self, ro, Lk, T):
        """float64 variant of _uv_detect (cap 10 only, as validated on 9.50)"""
        best = None
        for ub in range(9, T - 160):
            if np.mean(np.abs(self.D(ro + ub)) < 1e-6) < 0.75: continue          # pre-filter only; _outline_ok >= 0.8 decides
            cap = 10; vb = ub + 8 * cap
            if vb + 8 * cap > T: break
            if np.mean((np.abs(self.D(ro + vb)) < 1e-6) & (np.abs(self.D(ro + vb + 8)) < 1e-6)) < 0.75: continue
            U = np.stack([self.D(ro + ub + 8 * i) for i in range(cap)], 1)
            V = np.stack([self.D(ro + vb + 8 * i) for i in range(cap)], 1)
            frac = float(np.mean(_outline_ok(U, V, Lk)))
            if frac >= 0.8 and (best is None or frac > best[0]): best = (frac, ub, vb, cap)
            if frac >= 0.8: break
        return best

    @staticmethod
    def _poly_offsets(lay):
        """-> (element size, cx, cy, type offsets) of a contour record layout"""
        cap, ub = lay['poly_cap'], lay['poly_ub']
        if lay.get('poly_f64'):
            cx = ub + 24 * cap; return 8, cx, cx + 4 * cap, cx + 8 * cap
        A = 4 * cap; return 4, ub + 3 * A, ub + 4 * A, ub + 5 * A

    def _detect_chamfers(self, lay, cp):
        """chamfer arrays follow u, v, w: x[cap], y[cap], type[cap] (7.82/8.07/8.53); the type
        array ends with INT_MAX right after the last point - require that on >= 80%."""
        cap, ub = lay['poly_cap'], lay['poly_ub']; A = 4 * cap; hit = tot = 0
        es, cxo, cyo, tyo = self._poly_offsets(lay); RD = self.D if es == 8 else self.F
        for m in cp[:300]:
            key = int(self.I([m['off'] + lay['poly_field']])[0]); S = lay['poly_stride']
            if lay.get('poly_field2'):
                r = int(self.lookup([key], S)[0])
                if r < 0: continue
                key = int(self.I([r + lay['poly_field2']])[0]); S = lay['poly_stride2']
            for r in self.lookup_all(key, S)[:1]:
                if int(self.I([r + 13])[0]) != 0: continue
                u = RD(r + ub + es * np.arange(cap)); v = RD(r + lay['poly_vb'] + es * np.arange(cap))
                n = 1
                while n < cap and not (abs(u[n]) < 1e-3 and abs(v[n]) < 1e-3): n += 1
                if n >= cap: continue
                tot += 1
                ty = self.I(r + tyo + 4 * np.arange(cap))
                hit += int(ty[n] == SENTINEL and all(t in (0, 10, 20, 30, 40, 50, 60, 70) for t in ty[:n]))
        if tot >= 3 and hit >= 0.8 * tot:
            lay['poly_ch'] = True

    def _uv_detect(self, ro, Lk, T):
        """-> (frac, ub, vb, cap) of the u[cap]/v[cap] float32 outline arrays in records ro."""
        best = None
        for ub in range(9, T - 16):
            if np.mean(np.abs(self.F(ro + ub)) < 1e-3) < 0.9: continue
            # 10 is the Tekla array size validated against IFC (7.82, 8.07, 8.53); a smaller
            # guess shifts v by one slot and still "passes" loose checks, so try 10 first
            for cap in [10] + [c for c in range(4, 41) if c != 10]:
                vb = ub + 4 * cap
                if vb + 4 * cap > T + 4: break
                v0, v1 = self.F(ro + vb), self.F(ro + vb + 4)
                if np.mean((np.abs(v0) < 1e-3) & (np.abs(v1) < 1e-3)) < 0.9: continue
                U = np.stack([self.F(ro + ub + 4 * i) for i in range(cap)], 1)
                V = np.stack([self.F(ro + vb + 4 * i) for i in range(cap)], 1)
                frac = float(np.mean(_outline_ok(U, V, Lk)))
                if frac >= 0.8 and (best is None or frac > best[0]):
                    best = (frac, ub, vb, cap)
                if frac >= 0.8: break
        return best

    def outline_points(self, lay, m):
        """raw contour points [(u, v, type, x, y)] of a contour plate, or None. The first record
        holds up to cap points; longer contours continue in records with the same key and a
        part index at +13; the chamfer-type array closes with INT_MAX."""
        if not lay.get('poly_stride'): return None
        key = int(self.I([m['off'] + lay['poly_field']])[0]); S = lay['poly_stride']
        if lay.get('poly_field2'):
            r = int(self.lookup([key], S)[0])
            if r < 0: return None
            key = int(self.I([r + lay['poly_field2']])[0]); S = lay['poly_stride2']
            if key <= 0: return None
        recs = self.lookup_all(key, S)
        if not recs: return None
        cap, ub, vb = lay['poly_cap'], lay['poly_ub'], lay['poly_vb']
        A = 4 * cap; ch = lay.get('poly_ch')
        es, cxo, cyo, tyo = self._poly_offsets(lay); RD = self.D if es == 8 else self.F
        byidx = {}
        for r in recs:
            byidx.setdefault(int(self.I([r + 13])[0]) if ch else 0, r)
        pts = []
        for k in range(len(byidx)):
            r = byidx.get(k)
            if r is None: break
            u = RD(r + ub + es * np.arange(cap)); v = RD(r + vb + es * np.arange(cap))
            if ch:
                ty = self.I(r + tyo + 4 * np.arange(cap)); cx = self.F(r + cxo + 4 * np.arange(cap)); cy = self.F(r + cyo + 4 * np.arange(cap))
                end = np.nonzero(ty == SENTINEL)[0]; n = int(end[0]) if len(end) else cap
                pts += [(float(u[i]), float(v[i]), int(ty[i]), float(cx[i]), float(cy[i])) for i in range(n)]
                if n < cap: break
            else:
                n = 1
                while n < cap and not (abs(u[n]) < 1e-3 and abs(v[n]) < 1e-3): n += 1
                pts += [(float(u[i]), float(v[i]), 0, 0.0, 0.0) for i in range(n)]
                break
        pts = [(0.0 if abs(p[0]) < 1e-3 else p[0], 0.0 if abs(p[1]) < 1e-3 else p[1]) + tuple(p[2:]) for p in pts]
        n = len(pts)
        if n < 3 or not all(np.isfinite(c) and abs(c) < 1e6 for p in pts for c in p[:2]): return None
        # 7.x: first edge = member length; 8.x: outline width = member length
        us = [p[0] for p in pts]
        if abs(pts[1][0] - m['L']) > 0.05 and abs((max(us) - min(us)) - m['L']) > 0.05: return None
        area = 0.5 * sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
        return pts if abs(area) > 1e-3 else None

    def polygon(self, lay, m):
        pts = self.outline_points(lay, m)
        if not pts: return None
        REPAIR_OK[0] = bool(m.get('cut')); LAST_REPAIR[0] = None          # cut-not-applied P14
        try:
            P = apply_chamfers(pts) if lay.get('poly_ch') else [p[:2] for p in pts]
        finally:
            REPAIR_OK[0] = False
        if LAST_REPAIR[0] is not None and P: self.__dict__.setdefault('repaired', {})[m.get('seq')] = LAST_REPAIR[0]
        return P if P and len(P) >= 3 else None      # None: refused (self-intersecting) or degenerate

    # Part cuts: Tekla stores each cutting body as a member with material ANTIMATERIAL and
    # links it to the member it cuts through a relation record (7.82: stride 69, parent @17,
    # cut @21 - 558/558 cut parts linked). Found per file: the (table, field, field) pair
    # whose records join cut-part keys to real-part keys.
    def find_cut_links(self, M):
        seq = lambda m: int(self.I([m['off'] + 9])[0])
        cuts = [m for m in M if m.get('cut')]
        if len(cuts) < 3: return {}
        ck = np.array(sorted({seq(m) for m in cuts}), np.int64)
        pk = np.array(sorted({seq(m) for m in M if not m.get('cut')}), np.int64)
        best = None
        for s, recs in self.runs:
            if s > 200 or len(recs) < 3: continue
            ints = {f: self.I(recs + f) for f in range(9, s - 3)}
            for f1, v1 in ints.items():
                m1 = inkeys(ck, v1)
                if m1.sum() < 3: continue
                for f2, v2 in ints.items():
                    if f2 == f1: continue
                    m2 = m1 & inkeys(pk, v2)
                    if m2.sum() >= 3 and (best is None or m2.sum() > best[0]):
                        best = (int(m2.sum()), s, f1, f2)
        if not best: return {}
        _, s, fc, fp = best
        links = collections.defaultdict(list)
        for st, recs in self.runs:
            if st != s: continue
            c = self.I(recs + fc); p = self.I(recs + fp)
            ok = inkeys(ck, c) & inkeys(pk, p)
            for a, b in zip(p[ok], c[ok]): links[int(a)].append(int(b))
        # cut-not-applied P5: isolated relation records. Objects edited after the last full save are written one by one at the end of
        # the file, outside the fixed-stride runs, so the run scan above misses their relation record (1d8972fb: 18 of 21 unlinked cut
        # parts). Same field layout (header flag byte 1/4/5 at +8, ids > 0 at +0/+4, cut key at fc, decoded non-cut part key at fp);
        # taken only when every such record naming the cut names the same parent.
        linked = {c for v in links.values() for c in v}
        K = np.array(sorted({int(c) for c in ck if int(c) not in linked}), np.int64)
        salv = 0
        if len(K):
            pks = set(int(x) for x in pk); found = collections.defaultdict(set); u8 = self.u8
            for a in range(4):
                n = (self.L - a) // 4
                for c0 in range(0, n, 16_000_000):
                    v = np.frombuffer(self.b, '<i4', count=min(16_000_000, n - c0), offset=a + 4 * c0)
                    i = np.searchsorted(K, v); i[i >= len(K)] = 0
                    for j in np.nonzero(K[i] == v)[0]:
                        st = a + 4 * (c0 + int(j)) - fc
                        if st < 0 or st + max(fp, fc) + 4 > self.L or int(u8[st + 8]) not in self.FLAGS: continue
                        if int(self.I([st])[0]) <= 0 or int(self.I([st + 4])[0]) <= 0: continue
                        par = int(self.I([st + fp])[0])
                        if par in pks: found[int(v[j])].add(par)
            for c, ps in found.items():
                if len(ps) == 1:
                    links[ps.pop()].append(c); salv += 1
        self.cut_layout = dict(stride=s, cut=fc, parent=fp, linked=int(sum(len(v) for v in links.values())), cuts=len(cuts), linked_isolated=salv)
        return {k: sorted(set(v)) for k, v in links.items()}

    def attr_strings(self, lay, pa_seq):
        o = int(self.lookup([pa_seq], lay['attr_stride'])[0])
        if o < 0: return {}
        return {m.start(): m.group().decode('latin1')
                for m in re.finditer(rb'[\x20-\x7e]{2,}', self.b[o:o + lay['attr_stride']])}


def _web_vertical(M):
    hz = [m for m in M if abs(m['x'][2]) < 0.1 and m['L'] > 500 and not m.get('cut')]
    return (sum(1 for m in hz if abs(m['y'][2]) > 0.996) / len(hz)) if len(hz) >= 20 else None


_BOLT_RE = re.compile(r'^MM\d')
AXIS_TOL_DEG = 15.0


def _axis_angles(db, pts, lay, M):
    """per member: angle (deg) between its csys x and its own reference line p1 -> p2; NaN when
    the line is too short to judge or the member is a bolt group (bolt groups are never written
    and their layout line is not their axis). End offsets tilt real members by a few degrees;
    an orientation record that belongs to another object gives arbitrary angles."""
    if not M or not pts: return np.full(len(M), np.nan)
    P = pts[lay.get('pts', 0)]
    offs = np.array([m['off'] for m in M]); X = np.array([m['xr'] for m in M])
    p1 = db._pt(P, db.I(offs + lay['p1'])); p2 = db._pt(P, db.I(offs + lay['p2']))
    d = p2 - p1; n = np.linalg.norm(d, axis=1)
    with np.errstate(invalid='ignore', divide='ignore'):
        ang = np.degrees(np.arccos(np.clip(np.abs((d / n[:, None] * X).sum(1)), 0, 1)))
    bolt = np.array([bool(m.get('prof') and _BOLT_RE.match(m['prof'])) for m in M])
    return np.where(np.isfinite(n) & (n > 1) & ~bolt, ang, np.nan)


def _axis_flags(db, pts, lay, M):
    """per member: False only when it is judged and more than AXIS_TOL_DEG off its own line"""
    ang = _axis_angles(db, pts, lay, M)
    return list(~(np.isfinite(ang) & (ang > AXIS_TOL_DEG)))


def _axis_agreement(db, pts, lay, M):
    """share of judged members (bolt groups excluded) within AXIS_TOL_DEG of their own reference
    line. The right orientation link gives 1.0 on every validated model (7.64-8.95); a wrong one
    gives ~0.1-0.3 even when its beams happen to stand web-vertical (8.65: +37/seq)."""
    if not M or not pts: return None
    ang = _axis_angles(db, pts, lay, M)
    ok = np.isfinite(ang)
    if ok.sum() < 10: return None
    return float(np.mean(ang[ok] <= AXIS_TOL_DEG))


def _accept(db, lay, m):
    """a layout is accepted when its members' part records rebuild profiles: judged only on
    members whose type record IS in the part-type table (bolt groups live in another table)."""
    if not m: return False
    withp = sum(1 for x in m if x['prof'])
    if withp == 0: return False
    # names only come back through the strtok identity (random bytes cannot pass it), so a
    # majority of members with rebuilt names is strong evidence; bolt groups whose type
    # records sit in a same-width table are the usual remainder
    if withp >= 0.5 * len(m): return True
    inattr = [x for x in m if x.get('attr') is not None and db.lookup_all(x['attr'], lay['attr_stride'])]
    return bool(inattr) and sum(1 for x in inattr if x['prof']) >= 0.9 * len(inattr)


def _semi(db, base):
    """Known member geometry (stride/xyz/p1/p2/points/csys table) but re-detect the csys field
    + key and the profile fields. Seconds, vs minutes for a full discovery."""
    pts = db.find_points(fixed=(base['pts_stride'], base['pts_k']))
    if not pts: return None, None, None
    cs = db.find_csys(only=(base.get('csys_stride') or 61, base.get('csys_k') or 9))
    recs = db.bystride.get(base['stride'])
    if recs is None or not len(recs) or not cs: return None, None, None
    Ln = db.D(recs + base['xyz'] + 24)
    d = np.linalg.norm(db._pt(pts[0], db.I(recs + base['p1'])) - db._pt(pts[0], db.I(recs + base['p2'])), axis=1)
    if np.mean(np.abs(d - Ln) < 1.0) < 0.3: return None, None, None
    cands = []
    for ci, C in enumerate(cs):
        for f in range(9, base['stride'] - 3):
            if base['xyz'] - 4 < f < base['xyz'] + 32 or f in (base['p1'], base['p2']): continue
            fr = inkeys(C['keys'], db.I(recs + f)).mean()
            if fr > 0.1: cands.append((fr, f, ci))   # member runs also hold non-part records (8.65: 27% parts)
    # coverage alone picks wrong links (8.53: +37/seq covers 99.7% but gives 0% vertical webs,
    # +33/after covers 80% and is IFC-exact); score each candidate by web-vertical plausibility
    best = None
    for fr, f, ci in sorted(cands, reverse=True)[:8]:
        trial = dict(stride=base['stride'], xyz=base['xyz'], pts=0, p1=base['p1'], p2=base['p2'], csys=f,
                     csys_key=cs[ci]['key'], csys_stride=cs[ci]['stride'], csys_k=cs[ci]['k'])
        Mt = members(db, pts, cs, trial)
        ag = _axis_agreement(db, pts, trial, Mt)
        wv = _web_vertical(Mt)
        sc = (round(ag, 2) if ag is not None else 0.0, wv if wv is not None else 0.5, fr)
        if best is None or sc > best[0]: best = (sc, f, ci, fr)
    if not best or best[0][0] < 0.9: return None, None, None
    _, f, ci, fr = best
    lay = dict(stride=base['stride'], xyz=base['xyz'], pts_stride=base['pts_stride'], pts_k=base['pts_k'], pts=0,
               p1=base['p1'], p2=base['p2'], csys=f, csys_key=cs[ci]['key'], csys_stride=cs[ci]['stride'],
               csys_k=cs[ci]['k'], csys_frac=round(float(fr), 3), n=int(len(recs)), semi=True)
    db._member_run = recs
    db.find_attr(lay)
    return pts, cs, lay


def decode(path_or_bytes, layout=None, variants=(), allow_full=True):
    """-> (db, pts, cs, lay). Tries the version layout and every other known variant
    (verified per file: members must resolve and >=80% must rebuild a profile), then a
    semi-fast re-detection on known geometry, then full discovery."""
    data = load(path_or_bytes) if isinstance(path_or_bytes, str) else path_or_bytes
    db = Db(data); db.segment()
    tried = []; seen = set()
    KEYS = ('stride', 'xyz', 'p1', 'p2', 'csys', 'csys_key', 'csys_stride', 'csys_k', 'pts_stride', 'pts_k',
            'attr', 'attr_stride', 'prof_off', 'rest_ref', 'rest_stride', 'rest_off')
    for cand in [layout] + [v for v in variants if v != layout]:
        if not cand or not cand.get('csys_stride') or not cand.get('attr_stride'): continue
        sig = tuple(cand.get(k) for k in KEYS)
        if sig in seen: continue        # versions share layouts: decode each distinct one once
        seen.add(sig)
        pts = db.find_points(fixed=(cand['pts_stride'], cand['pts_k']))
        if not pts: continue
        cs = db.find_csys(only=(cand['csys_stride'], cand['csys_k']))
        lay = dict(cand); lay['pts'] = 0
        recs = db.bystride.get(lay['stride'])
        if recs is None or not len(recs): continue
        db._member_run = recs
        m = members(db, pts, cs, lay)
        tried.append((cand.get('stride'), cand.get('csys'), len(m)))
        ag = _axis_agreement(db, pts, lay, m) if m else None
        if _accept(db, lay, m) and (ag is None or ag >= 0.9):
            lay['fast'] = True; lay['fast_members'] = len(m); lay['axis_agreement'] = ag
            if not lay.get('poly_stride'): db.find_polygons(lay, m)
            return db, pts, cs, lay
    seen = set()
    for base in [layout] + list(variants):
        if not base: continue
        sig = tuple(base.get(k) for k in ('stride', 'xyz', 'p1', 'p2', 'pts_stride', 'pts_k', 'csys_stride', 'csys_k'))
        if sig in seen: continue
        seen.add(sig)
        pts, cs, lay = _semi(db, base)
        if lay and lay.get('attr_stride'):
            m = members(db, pts, cs, lay)
            if _accept(db, lay, m):
                db.find_polygons(lay, m); lay['tried'] = tried
                return db, pts, cs, lay
    r = _variant_retry(data, layout, variants, tried)
    if r is not None:
        return r
    if not allow_full:
        return db, [], [], {'tried': tried, 'status_hint': 'needs_full_discovery'}
    cs = db.find_csys()
    pts = db.find_points()
    lay = db.find_members(pts, cs) if pts else None
    if lay and lay['csys'] is not None:
        db.find_attr(lay)
        if lay.get('attr_stride'):
            db.find_polygons(lay, members(db, pts, cs, lay))
    if lay: lay['tried'] = tried
    return db, pts, cs, lay


# v2 (eng): record variants that the fixed layouts miss although the field layout is the same.
# Tried only after the normal fast and semi paths found nothing, so files that decode today are unchanged.
#   geo    : points at georeferenced coordinates beyond 1e8 mm (8.85: x 2.0e8, y 2.3e8 mm)
#   spread : the part csys run opens with other stride-61 records (8.85: 40+ pairs with dot 0.0045), so the
#            first-48 sample of the known csys table fails; judge it on a spread sample (rows still strict)
#   flag1  : live records carry header flag 0x01 (or 0x05) instead of 0x04 (8.07: 8,781 of 9,321 parts)
RETRY = (('spread', (4,), False, True), ('geo+spread', (4,), True, True), ('flag1+spread', (1, 4, 5), False, True),
         ('flag1+geo+spread', (1, 4, 5), True, True))


def _variant_retry(data, layout, variants, tried):
    seen = set()
    cands = []
    for cand in [layout] + [v for v in variants if v != layout]:
        if not cand or not cand.get('csys_stride') or not cand.get('attr_stride'): continue
        sig = tuple(cand.get(k) for k in ('stride', 'xyz', 'p1', 'p2', 'csys', 'csys_key', 'csys_stride', 'csys_k', 'pts_stride', 'pts_k',
                                         'attr', 'attr_stride', 'prof_off', 'rest_ref', 'rest_stride', 'rest_off'))
        if sig in seen: continue
        seen.add(sig); cands.append(cand)
    for name, flags, geo, spread in RETRY:
        db = Db(data); db.SEG_FLAGS = flags; db.CSYS_SPREAD = spread
        if geo: db.PLAUS_MAX = db.GEO_MAX
        db.segment()
        for cand in cands:
            pts = db.find_points(fixed=(cand['pts_stride'], cand['pts_k']))
            if not pts: continue
            cs = db.find_csys(only=(cand['csys_stride'], cand['csys_k']))
            lay = dict(cand); lay['pts'] = 0
            recs = db.bystride.get(lay['stride'])
            if recs is None or not len(recs): continue
            db._member_run = recs
            m = members(db, pts, cs, lay)
            tried.append((name, cand.get('stride'), cand.get('csys'), len(m)))
            ag = _axis_agreement(db, pts, lay, m) if m else None
            seqs = [x['seq'] for x in m]
            if _accept(db, lay, m) and ag is not None and ag >= 0.9 and len(set(seqs)) == len(seqs):
                lay['fast'] = True; lay['fast_members'] = len(m); lay['axis_agreement'] = ag
                lay['variant'] = name; lay['tried'] = tried
                if not lay.get('poly_stride'): db.find_polygons(lay, m)
                return db, pts, cs, lay
    return None


def members(db, pts, cs, lay):
    """Apply the member layout to every run it validates on (several tables share
    the member prefix layout), keeping records whose points, csys, length resolve."""
    if not lay or lay.get('csys') is None: return []
    k = lay['xyz']; P = pts[lay['pts']]
    need = max(k + 32, lay['p1'] + 4, lay['p2'] + 4, lay['csys'] + 4, (lay.get('attr') or 0) + 4)
    C = next((c for c in cs if c['stride'] == lay.get('csys_stride') and c['k'] == lay.get('csys_k') and c['key'] == lay['csys_key']), None)
    if C is None: return []
    cmap, ckeys = C['map'], C['keys']
    rows = []; seen = set()
    for s, recs in db.runs:
        if s < need: continue
        X = np.stack([db.D(recs + k + 8 * i) for i in range(4)], 1)
        p1 = db._pt(P, db.I(recs + lay['p1'])); p2 = db._pt(P, db.I(recs + lay['p2']))
        Cv = db.I(recs + lay['csys'])
        ok = (np.all(np.isfinite(X), 1) & (X[:, 3] > 0) & (np.abs(X[:, :3]) < db.PLAUS_MAX).all(1)
              & np.all(np.isfinite(p1), 1) & np.all(np.isfinite(p2), 1) & inkeys(ckeys, Cv))
        if ok.mean() < 0.5: continue
        A = db.I(recs + lay['attr']) if lay.get('attr') is not None else None
        for i in np.nonzero(ok)[0]:
            off = int(recs[i])
            if off in seen: continue
            seen.add(off)
            rows.append((off, s, X[i], p1[i], p2[i], int(Cv[i]), int(A[i]) if A is not None else None))
    if lay.get('attr_stride') and lay.get('attr') is not None:
        db.prefetch_attr(lay, [r[6] for r in rows])
    out = []; pcache = {}
    for off, s, Xi, p1i, p2i, ci, a in rows:
        O = Xi[:3]; L = Xi[3]; x, y = cmap[ci]
        y = y - (y @ x) * x; y = y / np.linalg.norm(y)
        Lr = (p2i - p1i) @ x; t0 = (O - p1i) @ x
        sgn = 1 if abs(t0) <= abs(t0 - Lr) else -1
        prof = None; cut = False
        if a is not None and lay.get('attr_stride'):
            if a not in pcache: pcache[a] = (db.profile(lay, a), db.is_cut(lay, a))
            prof, cut = pcache[a]
        out.append(dict(off=off, stride=s, O=O, E=O + sgn * x * L, x=sgn * x, xr=x, sgn=sgn, y=y, L=float(L),
                        prof=prof, cut=cut, attr=a, seq=int(db.I([off + 9])[0])))
    return out
