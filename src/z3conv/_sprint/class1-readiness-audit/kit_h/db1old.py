"""Old Xsteel .db1 reader (engines 6.x - 7.4x): record = 1-byte prefix + body, fixed
strides per engine. Port of the old C# Db1Reader layouts (derived there against Tekla's
ASCII dump) with two fixes that caused its 320 failures:
  * no 20,000,000 object-id ceiling (long-lived models exceed it -> "no part table")
  * profiles resolve through the harvested Tekla catalog (the old converter only knew
    parametric strings -> "no solids written")
Emits the same member dicts as db1dec.members() so db1step writes them unchanged.
"""
import re, collections, numpy as np
from db1dec import load

PART_NEW = dict(stride=228, attr=4, p1=8, p2=12, poly=16, csa=20, csys=24)    # 7.1 <= v < 7.5
PART_OLD = dict(stride=121, attr=4, p1=12, p2=16, poly=28, csa=32, csys=40)    # v < 7.1


class Old:
    def __init__(self, data):
        self.b = data; self.N = len(data)
        u8 = np.frombuffer(data, np.uint8); self.u8 = u8
        n = self.N - 8
        self.I_all = np.empty(n, np.int64); self.D_all = np.empty(n, np.float64); self.F_all = np.empty(n, np.float32)
        for k in range(4):
            v = np.frombuffer(data, '<i4', count=(self.N - k) // 4, offset=k); self.I_all[k::4] = v[:len(self.I_all[k::4])]
            f = np.frombuffer(data, '<f4', count=(self.N - k) // 4, offset=k); self.F_all[k::4] = f[:len(self.F_all[k::4])]
        for k in range(8):
            v = np.frombuffer(data, '<f8', count=(self.N - k) // 8, offset=k); self.D_all[k::8] = v[:len(self.D_all[k::8])]

    def I(self, o): return self.I_all[o]
    def D(self, o): return self.D_all[o]

    def runs(self, valid, stride, minrun=6):
        """offsets of records in contiguous runs (>= minrun) of validating records."""
        n = len(valid)
        ok = valid.copy()
        for k in range(1, minrun):
            sh = np.zeros(n, bool); sh[:n - k * stride] = valid[k * stride:]
            ok &= sh
        starts = np.nonzero(ok)[0]
        recs = set()
        for s in starts:
            if s in recs: continue
            p = int(s)
            while p < n and valid[p]:
                recs.add(p); p += stride
        return np.array(sorted(recs), np.int64)

    def cstr(self, o, n):
        # db1prof-patch: Latin-1 letters kept ('R.B \xd820' = 'R.B Ø20'; the ASCII-only cut gave 'R.B ')
        if True:
            import db1prof
            return db1prof.latin1_cstr(self.b, o, n)
        e = self.b.find(b'\0', o, o + n)
        s = self.b[o:e if e >= 0 else o + n]
        out = []
        for c in s:
            if c < 32 or c > 126: break
            out.append(chr(c))
        return ''.join(out)


def read(path_or_bytes, engine):
    data = load(path_or_bytes) if isinstance(path_or_bytes, str) else path_or_bytes
    o = Old(data); N = len(o.I_all) - 400
    P = PART_NEW if engine >= 7.1 else PART_OLD
    idx = np.arange(N)
    I, D = o.I_all, o.D_all
    # ---- point: id@0 vis@4 x,y,z@8 (stride 33)
    pv = np.zeros(N, bool)
    pv[:N - 32] = (I[:N - 32] > 0) & (I[4:N - 28] >= 0) & (I[4:N - 28] <= 64)
    for k in (8, 16, 24):
        v = D[k:N - 32 + k]; pv[:N - 32] &= np.isfinite(v) & (np.abs(v) < 1e8)
    pts_off = o.runs(pv, 33)
    # a point id can occur more than once in the stride-33 scan: the live record (plain doubles) and stray copies inside
    # free / unrelated blocks whose doubles are denormals (random bytes, ~1e-310 = the origin). Keeping the LAST copy let a
    # stray copy replace the real point -> member reference line ends at (0,0,0) -> part dropped by the axis guard.
    # A clean copy (every coordinate 0 or |v| > 1e-100) always wins over a stray one; ids without a clean copy are unchanged.
    pts = {}; clean_ids = set()
    for q in pts_off:
        q = int(q); pid = int(I[q])
        clean = all(D[q + k] == 0 or abs(D[q + k]) > 1e-100 for k in (8, 16, 24))
        if pid in clean_ids and not clean:
            continue
        pts[pid] = np.array([D[q + 8], D[q + 16], D[q + 24]])
        if clean:
            clean_ids.add(pid)
    # ---- coordsys_attr: xdir@0 ydir@24 id@48 (stride 53)
    cv = np.zeros(N, bool); M = N - 60
    x = np.stack([D[k:M + k] for k in (0, 8, 16)], 1); y = np.stack([D[k:M + k] for k in (24, 32, 40)], 1)
    with np.errstate(invalid='ignore', over='ignore'):
        cv[:M] = (np.abs((x * x).sum(1) - 1) < 0.02) & (np.abs((y * y).sum(1) - 1) < 0.02) & (I[48:M + 48] > 0)
    cs_off = o.runs(cv, 53)
    csa = {int(I[q + 48]): (np.array([D[q], D[q + 8], D[q + 16]]), np.array([D[q + 24], D[q + 32], D[q + 40]])) for q in cs_off}
    # ---- part_attr (stride 373): id@0 obj_type@4 form@8 npoints@72 ben@102 prof@124 mat@270
    av = np.zeros(N, bool); M = N - 380
    av[:M] = (I[:M] > 0) & (I[4:M + 4] >= 0) & (I[4:M + 4] <= 100) & (I[72:M + 72] >= 0) & (I[72:M + 72] <= 64)
    pr = o.u8[124:124 + M]; av[:M] &= (pr >= 32) & (pr <= 126)
    at_off = o.runs(av, 373)
    attrs = {}
    for q in at_off:
        attrs[int(I[q])] = dict(obj_type=int(I[q + 4]), form=int(I[q + 8]), npoints=int(I[q + 72]),
                                ben=o.cstr(q + 102, 22), prof=o.cstr(q + 124, 62), mat=o.cstr(q + 270, 22))
    # ---- partpolygon (stride 333): id@0 no@4 x[10]@12 y[10]@52 z[10]@92 (float32)
    gv = np.zeros(N, bool); M = N - 340
    gv[:M] = (I[:M] > 0) & (I[4:M + 4] >= 0) & (I[4:M + 4] <= 64)
    F = o.F_all
    for k in range(12, 132, 4):
        v = F[k:M + k]; gv[:M] &= np.isfinite(v) & (np.abs(v) < 1e7)
    pg_off = o.runs(gv, 333)
    polys = {}
    for q in pg_off:
        polys.setdefault(int(I[q]), []).append((int(I[q + 4]), [(float(F[q + 12 + 4 * i]), float(F[q + 52 + 4 * i]), float(F[q + 92 + 4 * i])) for i in range(10)]))
    # ---- relation (stride 17): type 11 = part cut, id1 = parent part, id2 = cutting part
    rv = np.zeros(N, bool); Mr = N - 20
    rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
    rel_off = o.runs(rv, 17)
    cut_rel = collections.defaultdict(list)
    for q in rel_off:
        if int(I[q + 4]) == 11: cut_rel[int(I[q + 8])].append(int(I[q + 12]))
    # ---- part
    s = P['stride']; M = N - s - 8
    qv = np.zeros(N, bool)
    ln = D[P['csys'] + 24:M + P['csys'] + 24]
    qv[:M] = (I[:M] > 0) & (I[P['attr']:M + P['attr']] > 0) & np.isfinite(ln) & (ln >= 0) & (ln < 1e6)
    for k in (0, 8, 16):
        v = D[P['csys'] + k:M + P['csys'] + k]; qv[:M] &= np.isfinite(v) & (np.abs(v) < 1e8)
    part_off = o.runs(qv, s)
    # salvage isolated part records whose references all resolve (as the C# reader did)
    extra = []
    cand = np.nonzero(qv)[0]
    have = set(int(x) for x in part_off)
    for q in cand:
        if int(q) in have: continue
        if int(I[q + P['attr']]) in attrs and int(I[q + P['p1']]) in pts and int(I[q + P['p2']]) in pts and int(I[q + P['csa']]) in csa:
            extra.append(int(q))
    out = []; seen = set()
    for q in list(part_off) + extra:
        q = int(q); pid = int(I[q])
        if pid in seen: continue
        a = attrs.get(int(I[q + P['attr']])); c = csa.get(int(I[q + P['csa']]))
        p1 = pts.get(int(I[q + P['p1']])); p2 = pts.get(int(I[q + P['p2']]))
        if a is None or c is None or p1 is None or p2 is None: continue
        seen.add(pid)
        O = np.array([D[q + P['csys']], D[q + P['csys'] + 8], D[q + P['csys'] + 16]]); L = float(D[q + P['csys'] + 24])
        xr, y = c
        xr = xr / np.linalg.norm(xr); y = y - (y @ xr) * xr; y = y / np.linalg.norm(y)
        Lr = (p2 - p1) @ xr; t0 = (O - p1) @ xr
        dl = float(np.linalg.norm(p2 - p1))
        # within 15 deg of its own reference line (end offsets tilt real members a little);
        # bolt groups are never written and their layout line is not their axis
        axis_ok = None if (dl <= 1 or a['obj_type'] == 10 or (a['prof'] or '').startswith('MM')) else bool(abs(Lr) / dl > np.cos(np.radians(15)))
        sgn = 1 if abs(t0) <= abs(t0 - Lr) else -1
        poly = None
        if a['npoints'] > 0 and int(I[q + P['poly']]) in polys:
            raw = []
            for no, pts10 in sorted(polys[int(I[q + P['poly']])]):
                for pnt in pts10:
                    if len(raw) < a['npoints']: raw.append(pnt)
            poly = raw
        out.append(dict(off=q, stride=s, O=O, E=O + sgn * xr * L, x=sgn * xr, xr=xr, sgn=sgn, y=y, L=L, mat=a['mat'] or None, ben=a['ben'] or None,
                        prof=a['prof'] or None, cut=(a['mat'] == 'ANTIMATERIAL'), bolt=(a['obj_type'] == 10),
                        form=a['form'], old_poly=poly, attr=int(I[q + P['attr']]), pid=pid, axis_ok=axis_ok))
    ax = [m['axis_ok'] for m in out if m['axis_ok'] is not None]
    info = dict(points=len(pts), csys=len(csa), part_attr=len(attrs), polygons=len(polys), parts=len(out), salvaged=len(extra),
                axis_agreement=round(float(np.mean(ax)), 4) if len(ax) >= 10 else None,
                cut_relations=sum(len(v) for v in cut_rel.values()))
    return out, info, {k: v for k, v in cut_rel.items()}
