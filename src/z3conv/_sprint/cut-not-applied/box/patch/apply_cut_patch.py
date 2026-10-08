#!/usr/bin/env python3
"""apply_cut_patch.py KITDIR [--check] : apply the 'cut-not-applied' fixes to a DB1 fleet kit in place (db1old.py, db1dec.py, db1step.py).
Every edit is an exact-anchor string replacement; an anchor that is missing (kit changed) or already patched is reported and the
file is left untouched (no partial file). --check: report only.

Old engines (6.87 / 7.01 / 7.24 / 7.30, db1old):
  P1 polygon records: the live copy (prefix byte 4, not all-zero) of a (polygon id, no) wins over stray all-zero copies
     (axis-guard/cuts deep dive; 0762effe: the 1 unbuilt cut)
  P2 part-cut relations at stride 61 as well as 17: 7.2x/7.3x relation records carry a 44-byte string after id2 -> the stride-17
     scan found no type-11 record on any 7.24 / 7.30 model, so none of their cuts was applied
  P3 isolated live part_attr records referenced by live part records (edited objects appended one by one at the end of the file):
     parts and cut parts using them were dropped
  P4 a part whose attribute record has obj_type 11 (Tekla's boolean operative part, any material) and that a type-11 relation links
     to a parent is a cut part (written as steel before: D21 rung-hole cutters, copes, notches ...)
New engines (>= 7.5, db1dec): P5 isolated relation records of unlinked cut parts (same layout, one parent) are linked
Both (db1step): P6 a cut part whose profile is a bare number ('914.4', '111.600', '469.000') is a polygon cut of that depth
                P7 DB1_PART_CUTS=0 (diagnostics only) writes every part uncut
                P8 'F.B AxB' flat bars: thickness across the part (they were rotated 90 deg: rung holes through the 75 mm width)
                P10 a cut part with a zero-size profile ('PL0*177.8') removes nothing: counted apart, not as an unapplied cut
                P11 convert stats 'cut_stats': cut parts, bodies built, applied, unlinked, links to parts not written, operative parts
"""
import sys, os, re

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
    cut_rel = collections.defaultdict(list); rel_strides = {}
    for rs in (17, 61):
        n11 = 0
        for q in o.runs(rv, rs):
            if int(I[q + 4]) == 11:
                p_, c_ = int(I[q + 8]), int(I[q + 12])
                if c_ not in cut_rel[p_]: cut_rel[p_].append(c_)
                n11 += 1
        rel_strides[rs] = n11
    cut_rel = {k: v for k, v in cut_rel.items() if v}
    cut_children = {c_ for v in cut_rel.values() for c_ in v}
"""),
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
  ('P7 old-engine cuts',
"""        cuts = [cut_body[c] for c in cut_rel.get(m['pid'], []) if c in cut_body]
""",
"""        cuts = [cut_body[c] for c in cut_rel.get(m['pid'], []) if c in cut_body] if PART_CUTS_ON else []
"""),
 ],
}


def main():
    kit = sys.argv[1]; check = '--check' in sys.argv
    ok = True
    for fn, edits in PATCHES.items():
        p = os.path.join(kit, fn); s = open(p).read(); out = s; rep = []
        for name, old, new in edits:
            if new in out:
                rep.append(f'{name}: already applied'); continue
            n = out.count(old)
            if n != 1:
                rep.append(f'{name}: ANCHOR {"MISSING" if n == 0 else "AMBIGUOUS"} ({n})'); ok = False; continue
            out = out.replace(old, new); rep.append(f'{name}: ok')
        print(fn, '; '.join(rep))
        if not check and out != s and ok:
            compile(out, p, 'exec')
            open(p, 'w').write(out)
    print('RESULT', 'ok' if ok else 'FAILED (nothing written for failing files)')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
