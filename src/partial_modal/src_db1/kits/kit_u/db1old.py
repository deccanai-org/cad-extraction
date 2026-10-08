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


REL = {}                 # audit P1: relation pairs of the last read(): {10: [(id1, id2)], 11: [...]}

FIT = {}                 # cut-not-applied P13: Tekla fittings / line cuts of the last read(): {9: {part id: [(point, unit normal)]}, 12: {...}}


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
                                ben=o.cstr(q + 102, 22), prof=o.cstr(q + 124, 62), mat=o.cstr(q + 270, 22),
                                smask=int(I[q + 16]) if int(I[q + 4]) == 10 else None)   # tekla-slots: 'slotted holes in part 1..5' bits
    # ---- partpolygon (stride 333): id@0 no@4 x[10]@12 y[10]@52 z[10]@92 (float32)
    gv = np.zeros(N, bool); M = N - 340
    gv[:M] = (I[:M] > 0) & (I[4:M + 4] >= 0) & (I[4:M + 4] <= 64)
    F = o.F_all
    for k in range(12, 132, 4):
        v = F[k:M + k]; gv[:M] &= np.isfinite(v) & (np.abs(v) < 1e7)
    pg_off = o.runs(gv, 333)
    polys = {}; live = set(); CHAM = {}
    for q in pg_off:
        q = int(q); gid, no = int(I[q]), int(I[q + 4])
        p10 = [(float(F[q + 12 + 4 * i]), float(F[q + 52 + 4 * i]), float(F[q + 92 + 4 * i])) for i in range(10)]
        lv = data[q - 1] == 4 and any(c != 0 for p in p10 for c in p)
        CHAM[(gid, no)] = [int(I[q + 212 + 4 * i]) for i in range(10)]          # arc patch: chamfer type per point (40 = arc point)
        polys.setdefault(gid, []).append((no, p10, lv))
        if lv: live.add((gid, no))
    # cut-not-applied P1: a polygon (id, no) can occur more than once: the live record (prefix byte 4) and stray copies in free blocks
    # (prefix 0, all zeros). sorted() put the all-zero copy first -> a 65x65 cut outline read as 5 x (0,0,0) -> cut body unbuilt,
    # cut not applied (0762effe). Stray copies are dropped only where a live copy of the same (id, no) exists.
    polys = {g: [(no, p10) for no, p10, lv in v if lv or (g, no) not in live] for g, v in polys.items()}
    # ---- relation (stride 17): type 11 = part cut, id1 = parent part, id2 = cutting part
    rv = np.zeros(N, bool); Mr = N - 20
    rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
    rel_off = o.runs(rv, 61 if engine >= 7.1 else 17)          # audit P1: 7.1-7.4x relation records are stride 61 (id, type, id1, id2 + 44-byte tail)
    REL.clear()
    for q in rel_off:
        if int(I[q + 4]) in (10, 11): REL.setdefault(int(I[q + 4]), []).append((int(I[q + 8]), int(I[q + 12])))
    # cut-not-applied P2 (on top of audit P1's engine stride): type-11 part-cut relations are read at BOTH strides (17 up to 7.0x,
    # 61 on 7.2x / 7.3x: 44-byte string after id2), de-duplicated; the fleet run found type-11 records at one stride only per file
    # (6.87 / 7.01: 17, 7.24 / 7.30: 61), so this equals audit P1 on every data-3 model and also covers an engine at the boundary.
    cut_rel = collections.defaultdict(list); rel_strides = {}; fit_rel = {9: set(), 12: set()}
    for rs in (17, 61):
        n11 = 0
        for q in (rel_off if rs == (61 if engine >= 7.1 else 17) else o.runs(rv, rs)):
            t_ = int(I[q + 4])
            if t_ == 11:
                p_, c_ = int(I[q + 8]), int(I[q + 12])
                if c_ not in cut_rel[p_]: cut_rel[p_].append(c_)
                n11 += 1
            elif t_ in fit_rel: fit_rel[t_].add((int(I[q + 8]), int(I[q + 12])))       # cut-not-applied P13
        rel_strides[rs] = n11
    cut_rel = {k: v for k, v in cut_rel.items() if v}
    cut_children = {c_ for v in cut_rel.values() for c_ in v}
    # cut-not-applied P13: Tekla fittings (relation type 9) and line cuts (type 12): id1 = the part, id2 = a plane record (stride 41):
    # id@0, coordsys_attr id@4, plane point x,y,z@8/16/24 (doubles), plane size@32; plane normal = x cross y of that coordsys.
    # Proof (IRON_ORE_PELLETIZING 7.24 vs its own Tekla IFC, 2,108 fitting planes): with the part end moved to each perpendicular
    # fitting plane our length equals Tekla's 'Length' within 1 mm on 1,046 of 1,048 parts; 266 planes lie beyond the part end
    # (Tekla lengthens the part); line cuts: the part middle is on the -normal side on 24 / 24 (iron) and 143 / 144 (0762effe).
    FIT.clear(); fit_dec = collections.Counter()
    kids = np.array(sorted({c_ for v in fit_rel.values() for _, c_ in v}), np.int64)
    if len(kids):
        cand = collections.defaultdict(set); u8_ = o.u8
        hits_ = []
        for c0 in range(0, N - 40, 1 << 24):                         # chunked membership test (sorted keys, no full-size sort)
            blk = I[c0:min(N - 40, c0 + (1 << 24))]; j_ = np.searchsorted(kids, blk); j_[j_ >= len(kids)] = 0
            hits_.append(np.nonzero(kids[j_] == blk)[0] + c0)
        for q in np.concatenate(hits_) if hits_ else []:
            q = int(q)
            if q < 1 or u8_[q - 1] != 4 or int(I[q + 4]) not in csa: continue
            Pp = (float(D[q + 8]), float(D[q + 16]), float(D[q + 24]))
            if not all(np.isfinite(c) and abs(c) < 1e8 for c in Pp) or not any(c != 0 for c in Pp): continue
            cand[int(I[q])].add((Pp, int(I[q + 4])))
        for t_, pairs in fit_rel.items():
            for p_, c_ in sorted(pairs):
                cs_ = cand.get(c_)
                if not cs_: fit_dec['type%d_no_plane_record' % t_] += 1; continue
                if len(cs_) > 1: fit_dec['type%d_ambiguous' % t_] += 1; continue
                (Pp, k_), = cs_
                cx_, cy_ = csa[k_]; nv = np.cross(cx_, cy_); nn = float(np.linalg.norm(nv))
                if nn < 1e-9: fit_dec['type%d_degenerate' % t_] += 1; continue
                FIT.setdefault(t_, {}).setdefault(p_, []).append((np.array(Pp), nv / nn)); fit_dec['type%d' % t_] += 1
    # ---- part
    s = P['stride']; M = N - s - 8
    qv = np.zeros(N, bool)
    ln = D[P['csys'] + 24:M + P['csys'] + 24]
    qv[:M] = (I[:M] > 0) & (I[P['attr']:M + P['attr']] > 0) & np.isfinite(ln) & (ln >= 0) & (ln < 1e6)
    for k in (0, 8, 16):
        v = D[P['csys'] + k:M + P['csys'] + k]; qv[:M] &= np.isfinite(v) & (np.abs(v) < 1e8)
    part_off = o.runs(qv, s)
    # cut-not-applied P3: isolated live attribute records. Objects edited after the last full save are written one by one at the end
    # of the file, so their part_attr record is not in a run of 6 and the stride-373 scan missed it -> every part using it was dropped
    # (0762effe: 117 live part records, 26 of them parents of cuts: the ANGLE / BRACKET / BEAM parts of the model's own Tekla part
    # list). Taken only when the copy is live (prefix byte 4), passes the part_attr checks, names a profile, is the only live version
    # of that id, and the id is referenced by a live part record whose csys and both points resolve.
    need = collections.Counter()
    for q in np.nonzero(qv)[0]:
        q = int(q)
        if data[q - 1] == 4 and int(I[q + P['csa']]) in csa and int(I[q + P['p1']]) in pts and int(I[q + P['p2']]) in pts:
            a_ = int(I[q + P['attr']])
            if a_ not in attrs: need[a_] += 1
    iso = collections.defaultdict(list)
    if need:
        for q in np.nonzero(av)[0]:
            q = int(q)
            if data[q - 1] == 4 and int(I[q]) in need: iso[int(I[q])].append(q)
    attr_salvaged = attr_ambiguous = 0
    for a_, qs in iso.items():
        versions = {(int(I[q + 4]), o.cstr(q + 124, 62), o.cstr(q + 270, 22)) for q in qs}
        if len(versions) != 1:
            attr_ambiguous += 1; continue
        q = qs[-1]
        if not o.cstr(q + 124, 62): continue
        attrs[a_] = dict(obj_type=int(I[q + 4]), form=int(I[q + 8]), npoints=int(I[q + 72]),
                         ben=o.cstr(q + 102, 22), prof=o.cstr(q + 124, 62), mat=o.cstr(q + 270, 22),
                         smask=int(I[q + 16]) if int(I[q + 4]) == 10 else None)   # tekla-slots A: selection bits of salvaged records
        attr_salvaged += 1
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
        poly = None; poly_ch = None
        if a['npoints'] > 0 and int(I[q + P['poly']]) in polys:
            raw = []; rch = []
            for no, pts10 in sorted(polys[int(I[q + P['poly']])]):
                chs = CHAM.get((int(I[q + P['poly']]), no)) or [0] * 10
                for pnt, ch in zip(pts10, chs):
                    if len(raw) < a['npoints']: raw.append(pnt); rch.append(ch)
            poly = raw; poly_ch = rch
        out.append(dict(off=q, stride=s, O=O, E=O + sgn * xr * L, x=sgn * xr, xr=xr, sgn=sgn, y=y, L=L, mat=a['mat'] or None, ben=a['ben'] or None,
                        prof=a['prof'] or None, cut=(a['mat'] == 'ANTIMATERIAL' or (a['obj_type'] == 11 and pid in cut_children)),
                        bolt=(a['obj_type'] == 10), obj_type=a['obj_type'],
                        form=a['form'], old_poly=poly, old_poly_ch=poly_ch, attr=int(I[q + P['attr']]), pid=pid, axis_ok=axis_ok,
                        slot_mask=a.get('smask')))
    ax = [m['axis_ok'] for m in out if m['axis_ok'] is not None]
    info = dict(points=len(pts), csys=len(csa), part_attr=len(attrs), polygons=len(polys), parts=len(out), salvaged=len(extra),
                axis_agreement=round(float(np.mean(ax)), 4) if len(ax) >= 10 else None,
                cut_relations=sum(len(v) for v in cut_rel.values()), relation_type11_by_stride=rel_strides,
                attr_salvaged=attr_salvaged, attr_ambiguous=attr_ambiguous,
                cut_operative_parts=sum(1 for m in out if m['cut'] and m['mat'] != 'ANTIMATERIAL'))
    info['fittings_decoded'] = dict(fit_dec)                         # cut-not-applied P13
    return out, info, {k: v for k, v in cut_rel.items()}
