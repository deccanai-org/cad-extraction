"""builder_patch.py KIT_DIR : the audit's builder patches applied to a db1 kit copy in place (anchor-checked, idempotent).
P1 db1old.read  : relation table stride 61 for engines 7.1-7.4x (PART_NEW layout). Stride 17 finds 0 records there, so every Tekla cut
                  (ANTIMATERIAL part) of a 7.24 / 7.30 model was dropped (cuts_applied = 0) and its parent written uncut.
                  Type-10 (bolt group <-> bolted part) and type-11 (part <- cut) pairs are kept in db1old.REL.
P2 db1bolts.catalog_geometry : a model-catalog bolt whose head is 'ambiguous' (no s / k) -> None (standard table / nominal, tagged)
                  instead of KeyError 's' that fails the whole model (7c68f0c9874e: convert_error on codes i and j).
P3 db1bolts.BOLT_ENGINES += 7.30 : 7.30 bolt groups carry the same MM<d>*<L>/f1..f10 record.
P4 DB1_HOLE_REL (default 1): a bolt cuts a hole only in the parts Tekla bolts with its group (type-10 relation = the group's bolted-part
                  list); a group without any relation record keeps the geometric rule but only parts whose material along the axis
                  meets the decoded grip (f6 +- f10/2) - no holes in neighbours that only the protruding thread / nut side passes.
P5 DB1_POLYBEAM (default 1): old-engine polybeams (part form 4, >= 3 reference points; the points are world offsets from O and the
                  record length L is the FIRST segment only) are written along the whole stored polyline: one extrusion per segment,
                  mitred at the corners, united; holes searched on every segment. Tagged approx (bend chamfers are not in the record).
P6 DB1_HOLE_DEDUP (default 1): coaxial bolt holes in one part (axes parallel, < 1 mm apart, diameters within 0.6 mm) are cut once
                  (union extent); near-coincident pairs made OpenCASCADE booleans fail -> every L4-surface (no-solid) part of the
                  deployed code-i DB1 STEP. Pairs 0.01-1 mm apart are tagged approx on the part."""
import sys, os
d = sys.argv[1]


def patch(fn, pairs, tag):
    p = os.path.join(d, fn); t = open(p).read()
    if tag in t:
        return
    for a, n in pairs:
        assert t.count(a) == 1, f'{tag} anchor: {a[:60]!r}'
        t = t.replace(a, n)
    open(p, 'w').write(t); print(tag, 'applied to', fn)


patch('db1old.py', [
    ("    rel_off = o.runs(rv, 17)\n",
     "    rel_off = o.runs(rv, 61 if engine >= 7.1 else 17)          # audit P1: 7.1-7.4x relation records are stride 61 (id, type, id1, id2 + 44-byte tail)\n"
     "    REL.clear()\n"
     "    for q in rel_off:\n"
     "        if int(I[q + 4]) in (10, 11): REL.setdefault(int(I[q + 4]), []).append((int(I[q + 8]), int(I[q + 12])))\n"),
    ("def read(path_or_bytes, engine):\n",
     "REL = {}                 # audit P1: relation pairs of the last read(): {10: [(id1, id2)], 11: [...]}\n\n\ndef read(path_or_bytes, engine):\n")], 'audit P1')
patch('db1bolts.py', [
    ("    b, n1, w1 = e['bolt'], e['nut1'], e.get('washer1') or {}\n",
     "    b, n1, w1 = e['bolt'], e['nut1'], e.get('washer1') or {}\n"
     "    if not all(isinstance(b.get(k), (int, float)) for k in ('s', 'k')):\n"
     "        return None                      # audit P2: head ambiguous in the model catalog -> standard table / nominal (tagged), never a crash\n")], 'audit P2')
patch('db1bolts.py', [
    ("BOLT_ENGINES = {'6.87', '7.01', '7.24'}\n", "BOLT_ENGINES = {'6.87', '7.01', '7.24', '7.30'}          # audit P3: 7.30 bolt groups use the same record\n")], 'audit P3')

HELPER = r'''
POLY_TAG = ' [approx: polybeam - straight segments along the stored polyline, mitred corners (bend chamfers not decoded)]'   # audit P5


def _perp(v):
    v = np.asarray(v, float); a = np.array([1.0, 0, 0]) if abs(v[0]) < 0.9 else np.array([0, 1.0, 0])
    a = a - (a @ v) * v; return a / np.linalg.norm(a)


def polybeam_segments(m, outline):
    """audit P5: old-engine polybeam (form 4, >= 3 points = world offsets from O; the record length L is the first segment)
    -> ([{frame, depth, clips, hit_frame, hit_depth}], capped corners) | reason string"""
    P = [np.asarray(p, float) for p in (m.get('old_poly') or [])]
    Q = [P[0]] if P else []
    for p in P[1:]:
        if np.linalg.norm(p - Q[-1]) > 1e-6: Q.append(p)
    if len(Q) < 3: return 'lt3_points'
    O = np.asarray(m['O'], float); Wp = [O + q for q in Q]
    D = [Wp[k + 1] - Wp[k] for k in range(len(Wp) - 1)]; Ls = [float(np.linalg.norm(x)) for x in D]; D = [x / l for x, l in zip(D, Ls)]
    if abs(float(D[0] @ np.asarray(m['x'], float))) < 0.999 or abs(Ls[0] - m['L']) > 0.6: return 'frame_mismatch'
    if not outline or not outline[0]: return 'no_outline'
    R = max(math.hypot(a, b) for a, b in outline[0])
    y = np.asarray(m['y'], float); y = y - (y @ D[0]) * D[0]; y = y / np.linalg.norm(y); ys = [y]
    for k in range(1, len(D)):
        a = np.cross(D[k - 1], D[k]); s = float(np.linalg.norm(a)); c = float(D[k - 1] @ D[k]); yk = ys[-1]
        if s > 1e-9:
            a = a / s; th = math.atan2(s, c)
            yk = yk * math.cos(th) + np.cross(a, yk) * math.sin(th) + a * (a @ yk) * (1 - math.cos(th))
        yk = yk - (yk @ D[k]) * D[k]; ys.append(yk / np.linalg.norm(yk))
    sgn = m['sgn']; segs = []; capped = 0
    for k in range(len(D)):
        es = ee = 0.0; clips = []
        for j, end in ((k, 'start'), (k + 1, 'end')):
            if (end == 'start' and k == 0) or (end == 'end' and k == len(D) - 1): continue
            d0, d1 = D[j - 1], D[j]
            th = math.acos(float(np.clip(d0 @ d1, -1, 1)))
            if th > math.radians(150): capped += 1
            e = min(R * math.tan(min(th, math.radians(150)) / 2), 5 * R) + 1.0
            n = d0 + d1; n = n / np.linalg.norm(n) if np.linalg.norm(n) > 1e-9 else d0
            if end == 'start': es = e; clips.append((Wp[j], n, True))
            else: ee = e; clips.append((Wp[j], n, False))
        A = Wp[k] - D[k] * es; B = Wp[k + 1] + D[k] * ee; xr_k = sgn * D[k]; X = np.cross(xr_k, ys[k])
        segs.append({'frame': (B if sgn == 1 else A, -xr_k, X), 'depth': Ls[k] + es + ee, 'clips': clips,
                     'hit_frame': (Wp[k + 1] if sgn == 1 else Wp[k], -xr_k, X), 'hit_depth': Ls[k]})
    return segs, capped


def convert_old(data, out_ifc, cat, engine, t0):'''
ELEM = r'''    def element_poly(self, cls, name, frame0, segs, prof, cuts=()):
        """audit P5: polybeam = union of mitred segment extrusions in the frame of the first segment, then the cuts"""
        f = self.f; solid = None
        for sg in segs:
            ex = self.extrusion(prof, sg['depth'], self.relative(frame0, sg['frame']))
            for pt, nrm, keep_pos in sg['clips']:
                o_l, n_l, _x = self.relative(frame0, (pt, nrm, _perp(nrm)))
                ex = f.createIfcBooleanClippingResult('DIFFERENCE', ex, f.createIfcHalfSpaceSolid(f.createIfcPlane(self._p3((o_l, n_l, _perp(n_l)))), bool(keep_pos)))
            solid = ex if solid is None else f.createIfcBooleanResult('UNION', solid, ex)
        for cf, cp, cd in cuts:
            solid = f.createIfcBooleanResult('DIFFERENCE', solid, self.extrusion(cp, cd, self.cut_frame(frame0, cf)))
        rep = f.createIfcShapeRepresentation(self.ctx, 'Body', 'CSG', [solid])
        e = getattr(f, 'create' + cls)(ifcopenshell.guid.new(), self.oh, name or 'part', None, None,
                                         f.createIfcLocalPlacement(self.site_pl, self._p3(frame0)),
                                         f.createIfcProductDefinitionShape(None, None, [rep]), None)
        self.elems.append(e)
        return e

    def bolt_group(self, name, bolts):'''
P1_OLD = r'''            hit = HI.holes_for(b[0], b[2], reg)
            if hit:
                part_bolts[id(m)] = hit
                for i in hit:
                    sp = db1bolts.ply_check(b[0], b[2], reg, BL[i])
                    if sp:
                        spans[i].append(sp)
'''
P1_NEW = r'''            segs_ = POLY.get(id(m)) or [{'hit_frame': b[0], 'hit_depth': b[2]}]          # audit P5: every polybeam segment
            hf_ = {}
            for sg_ in segs_:
                for i in HI.holes_for(sg_['hit_frame'], sg_['hit_depth'], reg):
                    if i in hf_: HI.hits[i] -= 1
                    else: hf_[i] = (sg_['hit_frame'], sg_['hit_depth'])
            hit = list(hf_)
            if hit and HOLE_REL:                                   # audit P4: holes only in Tekla's bolted parts, within the grip
                keep = []
                for i in hit:
                    bb_ = BL[i]; g_ = REL10.get(bb_.get('pid'))
                    ok_ = m.get('pid') in g_ if g_ else True          # Tekla's bolted-part list is authoritative when the group has one
                    if ok_ and not g_ and bb_.get('axial_decoded') and bb_.get('grip'):   # no list: the part must meet the decoded grip
                        sp_ = db1bolts.ply_check(hf_[i][0], hf_[i][1], reg, bb_)
                        off_ = bb_['zh'] - bb_['L'] / 2
                        ok_ = sp_ is not None and sp_[1] >= bb_['grip'][0] - off_ - 1.0 and sp_[0] <= bb_['grip'][1] - off_ + 1.0
                    if ok_: keep.append(i)
                    else: HI.hits[i] -= 1; dropped_holes[0] += 1
                hit = keep
            if hit:
                part_bolts[id(m)] = hit
                for i in hit:
                    sp = db1bolts.ply_check(hf_[i][0], hf_[i][1], reg, BL[i])
                    if sp:
                        spans[i].append(sp)
'''
P2_OLD = r'''        for i in part_bolts.get(id(m), []):
            bb = BL[i]; dh, dec_ = db1bolts.hole_diameter(bb)
            holes_tol_decoded += 1 if dec_ else 0
            key = round(dh, 2)
            if key not in hole_prof:
                hole_prof[key] = out.profile('BOLT_HOLE_D%g' % key, 'CIRC', [dh / 2])
            ext = bb['L'] / 2 + 2 * bb['d']                      # through the whole grip (hole longer than the shank)
            cuts = cuts + [((bb['c'] - bb['ez'] * ext, bb['ez'], bb['ex']), hole_prof[key], 2 * ext)]
            holes_cut += 1
        cat_ = part_cat(m.get('prof'), b[3])
        cls = 'IfcPlate' if cat_ in ('connection', 'other') and b[3] not in ('parametric_stud_shank', 'parametric_anchor') else (
              'IfcMechanicalFastener' if b[3] in ('parametric_stud_shank', 'parametric_anchor') else 'IfcBeam')
        e = out.element(cls, approx_name(m['prof'], b[3]), b[0], b[1], b[2], cuts)
'''
P2_NEW = r'''        hc_ = []; near_ = 0.0
        for i in part_bolts.get(id(m), []):
            bb = BL[i]; dh, dec_ = db1bolts.hole_diameter(bb)
            holes_tol_decoded += 1 if dec_ else 0
            ext = bb['L'] / 2 + 2 * bb['d']                      # through the whole grip (hole longer than the shank)
            c_ = np.asarray(bb['c'], float); ez_ = np.asarray(bb['ez'], float); mg_ = False
            if HOLE_DEDUP:                                       # audit P6: a coaxial (< 1 mm) second hole is the same hole
                for h_ in hc_:
                    if abs(float(h_[1] @ ez_)) > 1 - 5e-7 and abs(h_[3] - dh) < 0.6:
                        w_ = c_ - h_[0]; s_ = float(w_ @ h_[1]); pp_ = float(np.linalg.norm(w_ - s_ * h_[1]))
                        if pp_ < 1.0:
                            near_ = max(near_, pp_, abs(h_[3] - dh)); h_[3] = max(h_[3], dh)
                            h_[4] = min(h_[4], s_ - ext); h_[5] = max(h_[5], s_ + ext); holes_merged[0] += 1; mg_ = True; break
            if not mg_:
                hc_.append([c_, ez_, np.asarray(bb['ex'], float), dh, -ext, ext])
            holes_cut += 1
        for h_ in hc_:
            key = round(h_[3], 2)
            if key not in hole_prof:
                hole_prof[key] = out.profile('BOLT_HOLE_D%g' % key, 'CIRC', [h_[3] / 2])
            cuts = cuts + [((h_[0] + h_[1] * h_[4], h_[1], h_[2]), hole_prof[key], h_[5] - h_[4])]
        cat_ = part_cat(m.get('prof'), b[3])
        cls = 'IfcPlate' if cat_ in ('connection', 'other') and b[3] not in ('parametric_stud_shank', 'parametric_anchor') else (
              'IfcMechanicalFastener' if b[3] in ('parametric_stud_shank', 'parametric_anchor') else 'IfcBeam')
        nm_ = approx_name(m['prof'], b[3])
        if near_ >= 0.01:
            nm_ += f' [approx: coincident bolt holes merged ({near_:.2f} mm apart)]'; near_merged[0] += 1
        if id(m) in POLY:
            e = out.element_poly(cls, nm_ + POLY_TAG, b[0], POLY[id(m)], b[1], cuts)
        else:
            e = out.element(cls, nm_, b[0], b[1], b[2], cuts)
'''
BODY_OLD = r'''        if prof is not None and BOLTS_ON:
            REGION[id(m)] = db1bolts.outline(kind, v)
        return (out.member_frame(m), prof, m['L'], how) if prof is not None else (None, 'writer_skip')

    REGION = {}
'''
BODY_NEW = r'''        if prof is not None and BOLTS_ON:
            REGION[id(m)] = db1bolts.outline(kind, v)
        if (POLYBEAM and prof is not None and not m.get('cut') and not isinstance(prof, db1prof.Frustum) and m.get('form') == 4
                and len(m.get('old_poly') or []) >= 3 and id(m) not in POLY_SEEN):          # audit P5
            POLY_SEEN.add(id(m)); r_ = polybeam_segments(m, db1bolts.outline(kind, v))
            if isinstance(r_, tuple):
                POLY[id(m)] = r_[0]; poly_stats['polybeams'] += 1; poly_stats['segments'] += len(r_[0]); poly_stats['corners_over_150deg'] += r_[1]
            else:
                poly_stats['polybeam_kept_straight_' + r_] += 1
        return (out.member_frame(m), prof, m['L'], how) if prof is not None else (None, 'writer_skip')

    REGION = {}
    POLYBEAM = os.environ.get('DB1_POLYBEAM', '1') == '1'; POLY = {}; POLY_SEEN = set(); poly_stats = collections.Counter()   # audit P5
    HOLE_DEDUP = os.environ.get('DB1_HOLE_DEDUP', '1') == '1'; holes_merged = [0]; near_merged = [0]                          # audit P6
'''
STAT_OLD = "    st.update(written=len(out.elems), sources=dict(src), skipped=dict(why), horizontal=len(hz), cuts_applied=applied,"
STAT_NEW = ("    st['audit_patch_stats'] = {'polybeam': dict(poly_stats), 'holes_merged': holes_merged[0], 'parts_with_near_coincident_holes_merged': near_merged[0],\n"
            "                               'holes_not_bolted_dropped': dropped_holes[0], 'hole_rule': 'type-10 bolted parts within the grip' if HOLE_REL else 'geometric',\n"
            "                               'relations_10': len(getattr(db1old, 'REL', {}).get(10, [])), 'relations_11': len(getattr(db1old, 'REL', {}).get(11, []))}\n" + STAT_OLD)
REL_OLD = "    part_bolts = {}; spans = [[] for _ in BL]\n"
REL_NEW = (REL_OLD + "    HOLE_REL = os.environ.get('DB1_HOLE_REL', '1') == '1'; dropped_holes = [0]        # audit P4\n"
           "    REL10 = collections.defaultdict(set)\n"
           "    for a_, b_ in getattr(db1old, 'REL', {}).get(10, []):\n"
           "        REL10[a_].add(b_); REL10[b_].add(a_)\n")
patch('db1step.py', [("\ndef convert_old(data, out_ifc, cat, engine, t0):", HELPER), ("    def bolt_group(self, name, bolts):", ELEM),
                     (BODY_OLD, BODY_NEW), (REL_OLD, REL_NEW), (P1_OLD, P1_NEW), (P2_OLD, P2_NEW), (STAT_OLD, STAT_NEW)], 'audit P4-P6')
