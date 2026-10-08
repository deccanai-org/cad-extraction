#!/usr/bin/env python3
"""apply_cut_patch.py KITDIR [--check] : apply the 'cut-not-applied' fixes to a DB1 fleet kit in place (db1old.py, db1dec.py, db1step.py)
and copy fittings.py (eng fork's decoder, unchanged) next to them. Every edit is an exact-anchor string replacement; entries of one
group are alternatives for different kit versions (P2: kits with / without audit P1). Missing / ambiguous anchor -> nothing written.
Re-running on a patched kit reports 'already applied'. --check: report only. Rebased on worker CODE z3-db1-2026-10-01n (also applies
to code m). Switches: DB1_PART_CUTS=0 (diagnostics: every part uncut), DB1_FITTINGS=0 (no fittings / line cuts).

Old engines (6.87 / 7.01 / 7.24 / 7.30, db1old):
  P1 polygon records: the live copy (prefix byte 4, not all-zero) of a (polygon id, no) wins over stray all-zero copies
     (axis-guard/cuts deep dive; 0762effe: the 1 unbuilt cut)
  P2 part-cut relations at stride 61 as well as 17 (on code n: on top of audit P1's engine stride; equal on all 106 data-3 models);
     also collects the type-9 / type-12 relations for P13
  P3 isolated live part_attr records referenced by live part records (edited objects appended one by one at the end of the file):
     parts and cut parts using them were dropped
  P4 a part whose attribute record has obj_type 11 (Tekla's boolean operative part, any material) and that a type-11 relation links
     to a parent is a cut part (written as steel before: D21 rung-hole cutters, copes, notches ...; none of the 1,174 such parts of the
     IRON_ORE model is in that model's own Tekla IFC export)
  P13 Tekla fittings (relation type 9) and line cuts (type 12): plane record (stride 41) id@0, coordsys id@4, point@8, size@32,
     normal = x cross y of the coordsys. Fittings move the part end to the plane (shorten or lengthen; oblique planes: extend + clip),
     line cuts remove the +normal side (end cuts: the end side). Writer in db1step (fit_old_plan).
New engines (>= 7.5, db1dec): P5 isolated relation records of unlinked cut parts (same layout, one parent) are linked
  P12 Tekla fittings (type 9) / line cuts (type 12) by the eng fork's fittings.py (handed to this stream; validated there vs Tekla IFC)
  P14 cut-part outlines whose arc through an arc point (type 40) crosses the neighbouring edges by a sliver (<= 0.25 mm wide, <= 1 %
      of the area) are kept with the sliver loops dropped (before: refused -> cut not applied); the parent is tagged [approx: ...]
Both (db1step): P6 a cut part whose profile is a bare number ('914.4', '111.600', '469.000') is a polygon cut of that depth
                P7 DB1_PART_CUTS=0 (diagnostics only) writes every part uncut
                P8 'F.B AxB' flat bars: thickness across the part (they were rotated 90 deg: rung holes through the 75 mm width)
                P9 'R.B <O-slash>20' / 'R.B 20' / 'R.BD20': round bar of that diameter (name = full section)
                P15 'PL a*b' beam-type plates: thickness = min(a, b) (Tekla's rule; rotated 90 deg when a > b)
                P10 a cut part with a zero-size profile ('PL0*177.8') removes nothing: counted apart, not as an unapplied cut
                P11 convert stats 'cut_stats': cut parts, bodies built, applied, unlinked, links to parts not written, operative parts;
                    'fittings': decoded planes, parts fitted, ends moved, lengthened / shortened, half-spaces applied
"""
import sys, os, re, collections

PATCHES = {
 'db1old.py': [
  ('P1 polygon live copy',
"""    polys = {}
    for q in pg_off:
        polys.setdefault(int(I[q]), []).append((int(I[q + 4]), [(float(F[q + 12 + 4 * i]), float(F[q + 52 + 4 * i]), float(F[q + 92 + 4 * i])) for i in range(10)]))
""",
"""    polys = {}; live = set()
    for q in pg_off:
        q = int(q); gid, no = int(I[q]), int(I[q + 4])
        p10 = [(float(F[q + 12 + 4 * i]), float(F[q + 52 + 4 * i]), float(F[q + 92 + 4 * i])) for i in range(10)]
        lv = data[q - 1] == 4 and any(c != 0 for p in p10 for c in p)
        polys.setdefault(gid, []).append((no, p10, lv))
        if lv: live.add((gid, no))
    # cut-not-applied P1: a polygon (id, no) can occur more than once: the live record (prefix byte 4) and stray copies in free blocks
    # (prefix 0, all zeros). sorted() put the all-zero copy first -> a 65x65 cut outline read as 5 x (0,0,0) -> cut body unbuilt,
    # cut not applied (0762effe). Stray copies are dropped only where a live copy of the same (id, no) exists.
    polys = {g: [(no, p10) for no, p10, lv in v if lv or (g, no) not in live] for g, v in polys.items()}
"""),
  ('P2 relations stride 17 + 61',
"""    # ---- relation (stride 17): type 11 = part cut, id1 = parent part, id2 = cutting part
    rv = np.zeros(N, bool); Mr = N - 20
    rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
    rel_off = o.runs(rv, 17)
    cut_rel = collections.defaultdict(list)
    for q in rel_off:
        if int(I[q + 4]) == 11: cut_rel[int(I[q + 8])].append(int(I[q + 12]))
""",
"""    # ---- relation: id@0 type@4 id1@8 id2@12; type 11 = part cut, id1 = parent part, id2 = cutting part.
    # cut-not-applied P2: stride 17 up to 7.0x; 7.2x / 7.3x relation records carry a 44-byte string after id2 -> stride 61 (on every
    # 7.24 / 7.30 model each cut part id is preceded by type 11 + its parent part id at stride 61 and no type-11 record exists at
    # stride 17, so the stride-17 scan alone left every cut of those engines unapplied). Both strides are scanned on every engine.
    rv = np.zeros(N, bool); Mr = N - 20
    rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
    cut_rel = collections.defaultdict(list); rel_strides = {}; fit_rel = {9: set(), 12: set()}
    for rs in (17, 61):
        n11 = 0
        for q in o.runs(rv, rs):
            t_ = int(I[q + 4])
            if t_ == 11:
                p_, c_ = int(I[q + 8]), int(I[q + 12])
                if c_ not in cut_rel[p_]: cut_rel[p_].append(c_)
                n11 += 1
            elif t_ in fit_rel: fit_rel[t_].add((int(I[q + 8]), int(I[q + 12])))       # cut-not-applied P13
        rel_strides[rs] = n11
    cut_rel = {k: v for k, v in cut_rel.items() if v}
    cut_children = {c_ for v in cut_rel.values() for c_ in v}
"""),
  ('P2 relations stride 17 + 61 (kit with audit P1, code n+)',
"""    cut_rel = collections.defaultdict(list)
    for q in rel_off:
        if int(I[q + 4]) == 11: cut_rel[int(I[q + 8])].append(int(I[q + 12]))
""",
"""    # cut-not-applied P2 (on top of audit P1's engine stride): type-11 part-cut relations are read at BOTH strides (17 up to 7.0x,
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
""", 'P2 relations stride 17 + 61'),
  ('P3 isolated live attribute records',
"""    part_off = o.runs(qv, s)
    # salvage isolated part records whose references all resolve (as the C# reader did)
""",
"""    part_off = o.runs(qv, s)
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
                         ben=o.cstr(q + 102, 22), prof=o.cstr(q + 124, 62), mat=o.cstr(q + 270, 22))
        attr_salvaged += 1
    # salvage isolated part records whose references all resolve (as the C# reader did)
"""),
  ('P4 obj_type-11 operative parts are cut parts',
"""prof=a['prof'] or None, cut=(a['mat'] == 'ANTIMATERIAL'), bolt=(a['obj_type'] == 10),""",
"""prof=a['prof'] or None, cut=(a['mat'] == 'ANTIMATERIAL' or (a['obj_type'] == 11 and pid in cut_children)),
                        bolt=(a['obj_type'] == 10), obj_type=a['obj_type'],"""),
  ('P2-P4 layout stats',
"""                cut_relations=sum(len(v) for v in cut_rel.values()))""",
"""                cut_relations=sum(len(v) for v in cut_rel.values()), relation_type11_by_stride=rel_strides,
                attr_salvaged=attr_salvaged, attr_ambiguous=attr_ambiguous,
                cut_operative_parts=sum(1 for m in out if m['cut'] and m['mat'] != 'ANTIMATERIAL'))"""),
  ('P13 FIT global (old engines)',
"""

def read(path_or_bytes, engine):
""",
"""
FIT = {}                 # cut-not-applied P13: Tekla fittings / line cuts of the last read(): {9: {part id: [(point, unit normal)]}, 12: {...}}


def read(path_or_bytes, engine):
"""),
  ('P13 fitting / line-cut planes (old engines)',
"""    cut_rel = {k: v for k, v in cut_rel.items() if v}
    cut_children = {c_ for v in cut_rel.values() for c_ in v}
""",
"""    cut_rel = {k: v for k, v in cut_rel.items() if v}
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
"""),
  ('P13 fitting decode statistics (old engines)',
"""                cut_operative_parts=sum(1 for m in out if m['cut'] and m['mat'] != 'ANTIMATERIAL'))
""",
"""                cut_operative_parts=sum(1 for m in out if m['cut'] and m['mat'] != 'ANTIMATERIAL'))
    info['fittings_decoded'] = dict(fit_dec)                         # cut-not-applied P13
"""),
 ],
 'db1dec.py': [
  ('P5 isolated relation records of unlinked cut parts',
"""        self.cut_layout = dict(stride=s, cut=fc, parent=fp, linked=int(sum(len(v) for v in links.values())), cuts=len(cuts))
        return {k: sorted(set(v)) for k, v in links.items()}
""",
"""        # cut-not-applied P5: isolated relation records. Objects edited after the last full save are written one by one at the end of
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
"""),
  ('P14 arc-outline sliver repair for cut parts (helpers)',
"""def _circ(a, b, c):""",
"""REPAIR_OK = [False]      # cut-not-applied P14: set by Db.polygon for cut parts only (contour plates keep the refusal)
LAST_REPAIR = [None]     # cut-not-applied P14: (dropped sliver area mm2, outline area mm2) of the last repaired outline


def _selfx_pair(P):
    \"\"\"first pair of properly crossing edges (i, j) of the closed polygon P, or None\"\"\"
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
    \"\"\"cut-not-applied P14: an arc through a contour's arc point (type 40) can poke a hair across the neighbouring straight edges
    (a944 HRH_MASTER 7.64: 68 'BL25' cutters, the arc A-B-C rises 0.11 mm above edge D-A and dips 0.1 mm under C-D) -> the outline
    crosses itself and the cut was refused. At each crossing the outline is split into its two loops and the thin one is dropped,
    only while every dropped loop is a sliver (width = 2 x area / its longest edge <= tol mm, area <= 1 % of the outline).
    -> (outline, total dropped area mm2) or (None, None)\"\"\"
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


def _circ(a, b, c):"""),
  ('P14 arc-outline sliver repair for cut parts (refusal)',
"""    if (len(corner) or any(t == 40 for t in T)) and _selfx(res) and not _selfx([(float(p[0]), float(p[1])) for p in P]):
        ARC_STATS["refused_selfx"] += 1
        return None
""",
"""    if (len(corner) or any(t == 40 for t in T)) and _selfx(res) and not _selfx([(float(p[0]), float(p[1])) for p in P]):
        if REPAIR_OK[0]:                                   # cut-not-applied P14: cut parts only
            rep, dev = _repair_slivers(res, {(float(p[0]), float(p[1])) for p in P})
            if rep is not None:
                ARC_STATS["selfx_repaired"] = ARC_STATS.get("selfx_repaired", 0) + 1; LAST_REPAIR[0] = (dev, abs(_area2(rep)))
                return rep
        ARC_STATS["refused_selfx"] += 1
        return None
"""),
  ('P14 arc-outline sliver repair for cut parts (polygon)',
"""        P = apply_chamfers(pts) if lay.get('poly_ch') else [p[:2] for p in pts]
        return P if P and len(P) >= 3 else None      # None: refused (self-intersecting) or degenerate
""",
"""        REPAIR_OK[0] = bool(m.get('cut')); LAST_REPAIR[0] = None          # cut-not-applied P14
        try:
            P = apply_chamfers(pts) if lay.get('poly_ch') else [p[:2] for p in pts]
        finally:
            REPAIR_OK[0] = False
        if LAST_REPAIR[0] is not None and P: self.__dict__.setdefault('repaired', {})[m.get('seq')] = LAST_REPAIR[0]
        return P if P and len(P) >= 3 else None      # None: refused (self-intersecting) or degenerate
"""),
 ],
 'db1step.py': [
  ('P6/P7 constants',
"""def section_for(name, cat):""",
"""# cut-not-applied P6: cut parts (ANTIMATERIAL / BlOpCl CUTPART) made by polygon cuts can carry their depth as a bare number instead of
# 'BL<t>' (component-made cuts '111.600', '469.000'; 8.53 '914.4' / '1016' / '1219.2' through 18-20 in pipes). The outline is the
# part's own contour record and a contour part's profile is its thickness, so they are built exactly like 'BL<t>' cuts.
P_CUTDEPTH = re.compile(r'^\\d+(?:\\.\\d+)?$')
PART_CUTS_ON = os.environ.get('DB1_PART_CUTS', '1') == '1'     # cut-not-applied P7, diagnostics only: '0' writes every part uncut


def zero_section(prof):
    \"\"\"cut-not-applied P10: a cut part whose own profile has a zero dimension ('PL0*177.8' on the 7.24 models) subtracts nothing:
    counted as cut_body_zero_thickness, not as an unapplied cut\"\"\"
    n = (prof or '').strip().upper()
    m = P_PLATE2.match(n) or P_PLATE1.match(n) or P_ROUND.match(n)
    return bool(m) and any(float(g) == 0.0 for g in m.groups() if g is not None)


def section_for(name, cat):"""),
  ('P6 new-engine body',
"""        kind, v, how = section_for(m['prof'], cat)
        if kind is None and v == 'contour_plate':
            poly = db.polygon(lay, m)""",
"""        kind, v, how = section_for(m['prof'], cat)
        if m.get('cut') and P_CUTDEPTH.match((m.get('prof') or '').strip()):
            kind, v, how = None, 'contour_plate', None          # cut-not-applied P6: polygon cut part named by its bare depth
        if kind is None and v == 'contour_plate':
            poly = db.polygon(lay, m)"""),
  ('P6 old-engine body',
"""        if m.get('bolt'): return (None, 'bolt_group_excluded')
        kind, v, how = section_for(m['prof'], cat)
        if kind is None and v == 'contour_plate':""",
"""        if m.get('bolt'): return (None, 'bolt_group_excluded')
        kind, v, how = section_for(m['prof'], cat)
        if m.get('cut') and P_CUTDEPTH.match((m.get('prof') or '').strip()):
            kind, v, how = None, 'contour_plate', None          # cut-not-applied P6: polygon cut part named by its bare depth
        if kind is None and v == 'contour_plate':"""),
  ('P7 new-engine cuts',
"""        cuts = [cut_body[c] for c in links.get(m['seq'], []) if c in cut_body]
""",
"""        cuts = [cut_body[c] for c in links.get(m['seq'], []) if c in cut_body] if PART_CUTS_ON else []
"""),
  ('P15 beam-type plate section: thickness = the smaller dimension',
"""    m = P_PLATE2.match(n)
    if m:  # beam-type plate: thickness first, width second (IFC XDim=t, YDim=b)
        t, b = float(m.group(1)), float(m.group(2))
        return 'RECT', [t, b], 'parametric'
""",
"""    m = P_PLATE2.match(n)
    if m:  # beam-type plate: thickness first, width second (IFC XDim=t, YDim=b)
        t, b = float(m.group(1)), float(m.group(2))
        # cut-not-applied P15: Tekla takes the smaller dimension as the thickness whatever the order ('PL177.8*9.525' = 'PL9.525*177.8'):
        # IRON_ORE 7.24 vs its own Tekla IFC: the 14 'PL a*b' parts with a > b stood rotated 90 deg (bbox y/z swapped), the 328 with
        # a < b matched; the holes and cuts of those plates were cut through the wrong face
        return 'RECT', [min(t, b), max(t, b)], 'parametric'
"""),
  ('P9 R.B round bars',
"""    n2 = re.sub(r'^F\.\s*B\.?\s*', 'FB', n)
    if n2 != n:""",
"""    # cut-not-applied P9: 'R.B \\xd820' (R.B + Latin-1 O-slash + 20) / 'R.B 20' / 'R.BD20' (Latin-1 names kept by db1prof) is a round bar of the stated diameter (the name
    # carries the full section). Unresolved before: steel round bars dropped, and the 7.01 operative rung-hole cutters 'R.B \\xd820'
    # (obj_type 11, P4) left cut_body_unbuilt (4fa8f263: 30, cc9bf730: 47).
    n3 = re.sub('^R\\\\.\\\\s*B\\\\.?\\\\s*(?:\\u00d8|DIA\\\\.?|D)?\\\\s*', 'RB', n)
    if n3 != n:
        m = P_ROUND.match(n3)
        if m: return 'CIRC', [float(m.group(1)) / 2], 'parametric'
    n2 = re.sub(r'^F\.\s*B\.?\s*', 'FB', n)
    if n2 != n:"""),
  ('P8 F.B flat bars: thickness across (like PL t*b)',
"""    n2 = re.sub(r'^F\.\s*B\.?\s*', 'FB', n)
    if n2 != n:
        m = P_PLATE2.match(n2)
        if m: return 'RECT', [float(m.group(1)), float(m.group(2))], 'parametric_flat_bar'""",
"""    n2 = re.sub(r'^F\.\s*B\.?\s*', 'FB', n)
    if n2 != n:
        m = P_PLATE2.match(n2)
        if m:
            # cut-not-applied P8: 'F.B 75X10' is width x thickness; the thickness lies across the part (XDim, local z) like 'PL t*b'.
            # Proof: Tekla's net weight of the e151a8fa ladder stringers F.B 75X10 (48.0 net / 48.7 gross kg) = 29 D21 rung holes
            # through 10 mm; with [75, 10] the same holes ran through 75 mm (45.3 kg); toe plates F.B 75X6 lay flat.
            a_, b_ = float(m.group(1)), float(m.group(2))
            return 'RECT', [min(a_, b_), max(a_, b_)], 'parametric_flat_bar'"""),
  ('P10 zero-thickness cut bodies (new engines)',
"""            if b[0] is not None: cut_body[m['seq']] = b[:3]
            else: why['cut_body_unbuilt'] += 1
""",
"""            if b[0] is not None: cut_body[m['seq']] = b[:3]
            else: why['cut_body_zero_thickness' if zero_section(m.get('prof')) else 'cut_body_unbuilt'] += 1   # cut-not-applied P10
"""),
  ('P10 zero-thickness cut bodies (old engines)',
"""            if b[0] is not None: cut_body[m['pid']] = b[:3]
            else: why['cut_body_unbuilt'] += 1
""",
"""            if b[0] is not None: cut_body[m['pid']] = b[:3]
            else: why['cut_body_zero_thickness' if zero_section(m.get('prof')) else 'cut_body_unbuilt'] += 1   # cut-not-applied P10
"""),
  ('P11 cut statistics (new engines)',
"""    st['parts_list'] = plist
    st['cuts_applied'] = applied
""",
"""    st['parts_list'] = plist
    st['cuts_applied'] = applied
    # cut-not-applied P11: every cut part accounted for (the grade flag cuts_not_applied only sees unbuilt bodies)
    _wr = {p[0] for p in plist if p[3] == 'written'}; _lk = {c for v in links.values() for c in v}
    st['cut_stats'] = dict(cut_parts=sum(1 for m in M if m.get('cut')), bodies_built=len(cut_body), applied=applied,
                           unlinked=sum(1 for m in M if m.get('cut') and m['seq'] not in _lk),
                           links_to_unwritten_parts=sum(1 for p, cs in links.items() if p not in _wr for c in cs if c in cut_body))
"""),
  ('P11 cut statistics (old engines)',
"""    st['parts_list'] = plist
    hz = [m for m in M if not m.get('cut') and abs(m['x'][2]) < 0.1 and m['L'] > 500]
""",
"""    st['parts_list'] = plist
    # cut-not-applied P11: every cut part accounted for (the grade flag cuts_not_applied only sees unbuilt bodies)
    _wr = {p[0] for p in plist if p[3] == 'written'}; _lk = {c for v in cut_rel.values() for c in v}
    st['cut_stats'] = dict(cut_parts=sum(1 for m in M if m.get('cut')), bodies_built=len(cut_body), applied=applied,
                           unlinked=sum(1 for m in M if m.get('cut') and m['pid'] not in _lk),
                           links_to_unwritten_parts=sum(1 for p, cs in cut_rel.items() if p not in _wr for c in cs if c in cut_body),
                           operative_parts=sum(1 for m in M if m.get('cut') and m.get('mat') != 'ANTIMATERIAL'))
    hz = [m for m in M if not m.get('cut') and abs(m['x'][2]) < 0.1 and m['L'] > 500]
"""),
  ('P12 fittings decode (new engines)',
"""    cut_body = {}
    for m in M:
        if m.get('cut'):
            b = body(m)
            if b[0] is not None: cut_body[m['seq']] = b[:3]
""",
"""    # cut-not-applied P12: Tekla fittings (relation type 9: planar end trims) and line cuts (type 12: plane cut, +normal side
    # removed) of the new engines, decoded by the eng fork's fittings.py (handed over to this stream; validated there against
    # Tekla IFC exports of 7.64 / 8.07 / 8.53 / 8.85 / 9.08 models). Perpendicular fittings on profile extrusions trim the member
    # (exact, no boolean), oblique ones / fittings on plates / line cuts are subtracted as half-space boxes. DB1_FITTINGS=0: off.
    FIT, LCUT, fit_info = {}, {}, {}
    fit_stats = collections.Counter(); FITP = {}
    if os.environ.get('DB1_FITTINGS', '1') == '1':
        try:
            import fittings as _fit
            FIT, LCUT, fit_info = _fit.decode_all(db, cs, lay, M)
            for m in M:
                if m.get('cut') or (m['seq'] not in FIT and m['seq'] not in LCUT): continue
                mm_, hs_, fn_ = _fit.plan(m, FIT.get(m['seq'], []), LCUT.get(m['seq'], []), extrusion=section_for(m['prof'], cat)[0] is not None)
                FITP[id(m)] = (mm_, hs_); fit_stats['parts'] += 1; fit_stats['trimmed'] += 'trim' in fn_; fit_stats['halfspaces'] += len(hs_)
        except Exception as ex_:
            FITP = {}; fit_info = dict(error=f'{type(ex_).__name__}: {str(ex_)[:200]}')
    cut_body = {}
    for m in M:
        if m.get('cut'):
            b = body(m)
            if b[0] is not None: cut_body[m['seq']] = b[:3]
"""),
  ('P12 fitted member bodies (new engines)',
"""        isbolt[id(m)] = BOLTS2 and is_bolt_record(m)
        if isbolt[id(m)]: continue
        bodies[id(m)] = body(m)
""",
"""        isbolt[id(m)] = BOLTS2 and is_bolt_record(m)
        if isbolt[id(m)]: continue
        bodies[id(m)] = body(FITP[id(m)][0] if id(m) in FITP else m)      # cut-not-applied P12: the fitted (trimmed) member
"""),
  ('P12 fitting half-spaces (new engines)',
"""        cuts = [cut_body[c] for c in links.get(m['seq'], []) if c in cut_body] if PART_CUTS_ON else []
        applied += len(cuts)
""",
"""        cuts = [cut_body[c] for c in links.get(m['seq'], []) if c in cut_body] if PART_CUTS_ON else []
        applied += len(cuts)
        if PART_CUTS_ON and FITP.get(id(m), (None, None))[1]:          # cut-not-applied P12: oblique fittings / line cuts
            size_ = 2.0 * (FITP[id(m)][0]['L'] + 2000.0)
            cuts = cuts + [_fit.halfspace_cut(out, P_, n_, size_) for P_, n_ in FITP[id(m)][1]]
            fit_stats['halfspaces_applied'] += len(FITP[id(m)][1])
"""),
  ('P12 fitting statistics (new engines)',
"""                           links_to_unwritten_parts=sum(1 for p, cs in links.items() if p not in _wr for c in cs if c in cut_body))
""",
"""                           links_to_unwritten_parts=sum(1 for p, cs in links.items() if p not in _wr for c in cs if c in cut_body))
    st['fittings'] = dict(fit_info, **fit_stats)                      # cut-not-applied P12
"""),
  ('P7 old-engine cuts',
"""        cuts = [cut_body[c] for c in cut_rel.get(m['pid'], []) if c in cut_body]
""",
"""        cuts = [cut_body[c] for c in cut_rel.get(m['pid'], []) if c in cut_body] if PART_CUTS_ON else []
"""),
  ('P13 old-engine fitting plan (constants)',
"""def approx_name(prof, how):""",
"""def section_radius(kind, v):
    \"\"\"cut-not-applied P13: a radius that bounds the section around the member axis (full height / width, so profile offsets are
    covered too); only sizes the extension of an oblique fitting, the half-space then clips the exact end\"\"\"
    try:
        if kind in ('CIRC', 'CHS'): return float(v[0])
        if kind == 'FRUSTUM': return max(float(v[0]), float(v[1])) / 2
        nums = [abs(float(c)) for c in _nums(v)]
        return float(math.hypot(*sorted(nums)[-2:])) if len(nums) >= 2 else 1000.0
    except Exception:
        return 1000.0


def fit_old_plan(m, fits, lcuts, kind, v):
    \"\"\"cut-not-applied P13 (old engines) -> (member to write, [(point, n_out)] half-spaces, notes). A Tekla fitting moves the part end
    to the fitting plane (shortens or lengthens the part); the side away from the part middle is removed. Perpendicular planes: the end
    is moved exactly (no boolean). Oblique planes: the end is extended past the plane by R tan(angle) + 1 mm and clipped by the plane.
    Line cuts remove the +normal side, except end cuts (axis crossing in the outer quarters) whose normal points at the part middle:
    there the end side is removed. Contour plates, polybeams and fitting planes within ~6 deg of the axis: half-spaces only.\"\"\"
    O, x, L = m['O'], m['x'], m['L']; mid = O + x * L / 2
    t0, t1 = 0.0, L; hs = []; notes = collections.Counter(); ends = collections.Counter()
    ext_ok = kind is not None and len(m.get('old_poly') or []) < 3
    R = section_radius(kind, v)
    for P, n in fits:
        n_out = n if float((mid - P) @ n) < 0 else -n
        c = float(n_out @ x)
        if not ext_ok or abs(c) < 0.1:
            hs.append((P, n_out)); notes['halfspace_only'] += 1; continue
        tp = float((P - O) @ n_out) / c
        perp = abs(abs(c) - 1) < 1e-6
        m_ = 0.0 if perp else R * math.sqrt(max(0.0, 1 - c * c)) / abs(c) + 1.0
        if c > 0: t1 = tp + m_; ends['end'] += 1; longer = tp > L + 1e-6
        else: t0 = tp - m_; ends['start'] += 1; longer = tp < -1e-6
        if not perp: hs.append((P, n_out))
        notes['perpendicular' if perp else 'oblique'] += 1; notes['lengthened' if longer else 'shortened'] += 1
    notes['same_end_twice'] += sum(1 for k_, n_ in ends.items() if n_ > 1)
    for P, n in lcuts:
        n = np.asarray(n, float); c = float(n @ x)
        tp = float((P - O) @ n) / c if abs(c) > 0.1 else None
        if float((mid - P) @ n) > 0 and tp is not None and (tp < 0.25 * L or tp > 0.75 * L):
            # an END cut whose stored normal points at the part middle: the end side is removed (0762effe L50*50*6 25281 carries the
            # same end plane twice with opposite normals; '+normal removed' deleted the whole part, Tekla's net weight 2.4 kg).
            # Cuts along the part or through its middle keep '+normal removed' (GSK 7.24: 8 HSS4X4X5/16 halved lengthwise).
            n = -n; notes['line_cut_end_normal_flipped'] += 1
        hs.append((P, n)); notes['line_cut'] += 1
    uniq = {}
    for P, n in hs: uniq.setdefault((round(float(P @ n), 2),) + tuple(np.round(n, 5)), (P, n))
    notes['halfspaces_deduplicated'] += len(hs) - len(uniq); hs = list(uniq.values())
    if t1 - t0 <= 1.0:
        notes['degenerate_kept_as_recorded'] += 1; return m, [], notes
    if abs(t0) < 1e-9 and abs(t1 - L) < 1e-9: return m, hs, notes
    return dict(m, O=O + x * t0, E=O + x * t1, L=float(t1 - t0)), hs, notes


def approx_name(prof, how):"""),
  ('P13 old-engine fitted members',
"""    cut_body = {}
    for m in M:
        if m.get('cut'):
            b = body(m)
            if b[0] is not None: cut_body[m['pid']] = b[:3]
""",
"""    # cut-not-applied P13: Tekla fittings (type 9) / line cuts (type 12) decoded by db1old.read (db1old.FIT). DB1_FITTINGS=0: off.
    FITP = {}; fit_stats = collections.Counter(); _FIT = getattr(db1old, 'FIT', {}) if os.environ.get('DB1_FITTINGS', '1') == '1' else {}
    if _FIT:
        import fittings as _fit
        for m in M:
            if m.get('cut') or m.get('bolt'): continue
            fl_ = _FIT.get(9, {}).get(m['pid'], []); lc_ = _FIT.get(12, {}).get(m['pid'], [])
            if not fl_ and not lc_: continue
            k_, v_, _h = section_for(m['prof'], cat)
            mm_, hs_, nt_ = fit_old_plan(m, fl_, lc_, k_, v_)
            FITP[id(m)] = (mm_, hs_); fit_stats['parts'] += 1; fit_stats['moved_ends'] += mm_ is not m; fit_stats['halfspaces'] += len(hs_)
            fit_stats.update(nt_)
    cut_body = {}
    for m in M:
        if m.get('cut'):
            b = body(m)
            if b[0] is not None: cut_body[m['pid']] = b[:3]
"""),
  ('P13 old-engine fitted member bodies',
"""        if m.get('cut') or (BOLTS_ON and m.get('bolt') and db1bolts.bolts_of(m)):
            continue
        bodies[id(m)] = body(m)
""",
"""        if m.get('cut') or (BOLTS_ON and m.get('bolt') and db1bolts.bolts_of(m)):
            continue
        if FITP.get(id(m), (m,))[0] is not m:                          # cut-not-applied P13: the fitted member; body() keys the section
            mm_ = FITP[id(m)][0]; bodies[id(m)] = body(mm_)              # region (bolt holes) and polybeam segments by id(member)
            if id(mm_) in REGION: REGION[id(m)] = REGION.pop(id(mm_))
            if id(mm_) in POLY: POLY[id(m)] = POLY.pop(id(mm_))
        else:
            bodies[id(m)] = body(m)
"""),
  ('P13 old-engine fitting half-spaces',
"""        cuts = [cut_body[c] for c in cut_rel.get(m['pid'], []) if c in cut_body] if PART_CUTS_ON else []
        applied += len(cuts)
""",
"""        cuts = [cut_body[c] for c in cut_rel.get(m['pid'], []) if c in cut_body] if PART_CUTS_ON else []
        applied += len(cuts)
        if PART_CUTS_ON and FITP.get(id(m), (None, None))[1]:          # cut-not-applied P13: oblique fittings / line cuts
            size_ = 2.0 * (FITP[id(m)][0]['L'] + 2000.0)
            cuts = cuts + [_fit.halfspace_cut(out, P_, n_, size_) for P_, n_ in FITP[id(m)][1]]
            fit_stats['halfspaces_applied'] += len(FITP[id(m)][1])
"""),
  ('P13 old-engine fitting statistics',
"""    hzI = [m for m in hz if m.get('prof') and section_for(m['prof'], cat)[0] == 'I']
""",
"""    st['fittings'] = dict(fit_stats, decoded=st['layout'].get('fittings_decoded'))      # cut-not-applied P13
    hzI = [m for m in hz if m.get('prof') and section_for(m['prof'], cat)[0] == 'I']
"""),
  ('P14 approx tag on parents of repaired cut outlines (new engines)',
"""        e = out.element(cls, approx_name(m['prof'], b[3]), b[0], b[1], b[2], cuts)
""",
"""        nm_n = approx_name(m['prof'], b[3])
        rp_ = [getattr(db, 'repaired', {})[c] for c in links.get(m['seq'], []) if c in cut_body and c in getattr(db, 'repaired', {})] if PART_CUTS_ON else []
        if rp_:                                                        # cut-not-applied P14
            nm_n += ' [approx: cut outline self-crossing slivers dropped (%.2f of %.0f mm2)]' % max(rp_); fit_stats['parts_with_repaired_cut_outline'] += 1
        e = out.element(cls, nm_n, b[0], b[1], b[2], cuts)
"""),
 ],
}


FILES = {'fittings.py': 'eng fork db1_v2/eng/fittings.py, unchanged (md5 cfc6cd23b9354728d183ceeb4e757fd6)'}


def main():
    """entries: (name, old, new[, group]); entries of the same group are alternatives (kit versions): exactly one must apply"""
    kit = sys.argv[1]; check = '--check' in sys.argv
    ok = True; outs = {}
    for fn, edits in PATCHES.items():
        p = os.path.join(kit, fn); s = open(p).read(); out = s; rep = []
        groups = collections.OrderedDict()
        for e in edits: groups.setdefault(e[3] if len(e) > 3 else e[0], []).append(e[:3])
        for gid, alts in groups.items():
            done = None
            for name, old, new in alts:
                if new in out: done = f'{name}: already applied'; break
            if done is None:
                for name, old, new in alts:
                    if out.count(old) == 1:
                        out = out.replace(old, new); done = f'{name}: ok'; break
            if done is None:
                done = ' / '.join(f'{name}: ANCHOR {"MISSING" if out.count(old) == 0 else "AMBIGUOUS"} ({out.count(old)})' for name, old, new in alts); ok = False
            rep.append(done)
        print(fn, '; '.join(rep)); outs[p] = (s, out)
    here = os.path.dirname(os.path.abspath(__file__))
    for fn, why in FILES.items():
        sp, dp = os.path.join(here, fn), os.path.join(kit, fn)
        if not os.path.exists(sp): print(fn, 'MISSING next to the patch script'); ok = False; continue
        same = os.path.exists(dp) and open(dp).read() == open(sp).read()
        print(fn, 'already present' if same else ('to copy' if check else 'copied'), '-', why)
        if not check and not same and ok: compile(open(sp).read(), dp, 'exec'); outs[dp] = (None, open(sp).read())
    if not check and ok:
        for p, (s, out) in outs.items():
            if out != s:
                compile(out, p, 'exec'); open(p, 'w').write(out)
    print('RESULT', 'ok' if ok else 'FAILED (nothing written)')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
