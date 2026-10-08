"""n5_sds2 (BACKUP_DATA ROOM_1021, SDS/2 7.245): AMBER estimates
  1. bar gratings GR1 1/2x35 13/16 (MISC #62) and GR1 1/2x21 9/16 (MISC #63, #67): RED (not built, the converter's
     plate fallback came out 5.7x the SDS/2 weight). The SDS/2 job stores each grating's vertices (no faces): 8-point
     boxes = 31 / 19 bearing bars 1.5 x 0.188 in, 4-point flat faces at the top = 59 cross bars 0.188 in wide, and the end
     bands. Rebuilt bar by bar from those records; the cross-bar DEPTH is not recorded (flat face) -> 1/4 in (estimated).
  2. MISC #61 GR1 1/2x35 13/16 (written as an outline-only plate): same piece name as MISC #62 -> #62's recorded bar layout
     on #61's own work line and length.
  3. JOIST #51 / #52 18K3: SDS/2 stores only the designation (vendor-designed joist). Depth 18 in, seat 2.5 in (SJI K
     series) on the recorded work line; chord angles, web rod and panel layout estimated to the SJI 18K3 weight 6.6 plf.
  4. BEAM #8 HSS5x5x1/4 (no fabricated pieces in the job): the tube of its twin BEAM #7 (same section, length, direction,
     elevation, roll; 76.2 mm in from each work point like every HSS5x5 beam of this length) moved onto #8's work line.
  5. MISC #30 Conc. 1.5 yards: the L x W x T prism kept (shape not recorded), labelled AMBER."""
import json
import math
import os

import numpy as np

import est_common as E

IN = 25.4


def ncl(v, tol=0.004):
    v = sorted(v)
    n = 1
    for a, b in zip(v, v[1:]):
        if b - a > tol:
            n += 1
    return n


def parse_grating(ev):
    """SDS/2 vertex records of a grating piece -> local (inch) boxes: bearing bars, cross-bar top faces, end bands"""
    V = np.array(ev['vertices']['world_mm'], float)
    pl = ev['placement']
    O = np.array(pl['origin_mm'], float)
    M = np.array(pl['rows_of_M'], float)
    L = (V - O) @ M.T / IN
    boxes, quads, loose = [], [], []
    i = 0
    while i < len(L):
        c8 = L[i:i + 8]
        if len(c8) == 8 and all(ncl(c8[:, k]) == 2 for k in range(3)):
            boxes.append((c8.min(0), c8.max(0)))
            i += 8
            continue
        c4 = L[i:i + 4]
        if len(c4) == 4 and ncl(c4[:, 2]) == 1 and ncl(c4[:, 0]) == 2 and ncl(c4[:, 1]) == 2:
            quads.append((c4.min(0), c4.max(0)))
            i += 4
            continue
        loose.append(L[i])
        i += 1
    lo, hi = L.min(0), L.max(0)
    return {'O': O, 'M': M, 'boxes': boxes, 'quads': quads, 'loose': np.array(loose), 'lo': lo, 'hi': hi}


def box_prism(O, X, Y, Z, lo, hi):
    """local inch box [lo, hi] in frame (O mm, X/Y/Z world unit axes) -> prism GEOM (outline at local z = lo[2])"""
    P = lambda x, y, z: (O + X * x * IN + Y * y * IN + Z * z * IN).tolist()
    outline = [E.r6(P(lo[0], lo[1], lo[2])), E.r6(P(hi[0], lo[1], lo[2])), E.r6(P(hi[0], hi[1], lo[2])), E.r6(P(lo[0], hi[1], lo[2]))]
    return {'kind': 'prism', 'outline_world': outline, 'normal': E.r6(Z.tolist()), 'thickness': round((hi[2] - lo[2]) * IN, 6)}


CB_DEPTH = 0.25     # in, estimated cross-bar depth (recorded only as a flat top face)


def grating_items(O, X, Y, Z, bars_y, length, width, depth, cross_x, cb_w):
    """bearing bars (y ranges), end bands, cross bars (x positions of their low edge), all in local inches"""
    items, vol = [], 0.0
    band = 0.1875
    for (y0, y1) in bars_y:
        lo, hi = np.array([band, y0, 0.0]), np.array([length - band, y1, depth])
        items.append(box_prism(O, X, Y, Z, lo, hi))
        vol += (hi - lo).prod()
    for x0 in (0.0, length - band):
        lo, hi = np.array([x0, -width, 0.0]), np.array([x0 + band, 0.0, depth])
        items.append(box_prism(O, X, Y, Z, lo, hi))
        vol += (hi - lo).prod()
    yin0, yin1 = min(a for a, _ in bars_y) + 0.0, max(b for _, b in bars_y)
    for x0 in cross_x:
        lo, hi = np.array([x0, yin0, depth - CB_DEPTH]), np.array([x0 + cb_w, yin1, depth])
        items.append(box_prism(O, X, Y, Z, lo, hi))
        vol += (hi - lo).prod()
    return items, vol * IN ** 3


def make(tag, *a):
    t = E.Tree(tag)
    fp = os.path.join(E.INPUTS, 'n5', 'sds2_facts.json')
    t.add_input(fp)
    d = json.load(open(fp))
    patch, log = E.new_patch(t), E.new_log(t)
    mem = {m['member']: m for m in d['members']}
    miss = {p['source_ref']: p for p in t.missing.get('parts', [])}

    # ---------------- 1. skipped gratings from their vertex records
    pattern = {}
    for s in d['skipped']:
        ev = s['source_evidence']
        g = parse_grating(ev)
        X, Y, Z = g['M'][0], g['M'][1], g['M'][2]
        length, width, depth = float(g['hi'][0]), float(-g['lo'][1]), float(g['hi'][2])
        bars_y = sorted((float(lo[1]), float(hi[1])) for lo, hi in g['boxes'])
        cross_x = sorted(float(lo[0]) for lo, hi in g['quads'])
        cb_w = float(np.median([hi[0] - lo[0] for lo, hi in g['quads']]))
        items, vol = grating_items(g['O'], X, Y, Z, bars_y, length, width, depth, cross_x, cb_w)
        wt = vol / IN ** 3 * E.STEEL_LB_PER_IN3
        pt = ev['piece_table']
        pattern[s['name']] = {'bars_y': bars_y, 'cross_x': cross_x, 'cb_w': cb_w, 'width': width, 'depth': depth,
                              'length': length, 'member': s['member']}
        ref = f"SDS/2 MISC #{s['member']}, piece {s['piece']}, inst {s['inst']}"
        mp = miss.get(ref)
        oid = f"est:grating:M{s['member']}:P{s['piece']}"
        basis = (f'estimated only where the job is silent: the SDS/2 job stores this grating as {len(ev["vertices"]["world_mm"])} '
                 f'vertices without faces; we read {len(g["boxes"])} 8-point boxes = bearing bars {bars_y[0][1] - bars_y[0][0]:.3f} x '
                 f'{depth:g} in, {len(g["quads"])} 4-point flat faces at the top = cross bars {cb_w:.3f} in wide at '
                 f'{(cross_x[1] - cross_x[0]) if len(cross_x) > 1 else 0:g} in, and {len(g["loose"])} loose points = the two end bands; '
                 f'the cross-bar depth is not recorded (flat face) -> {CB_DEPTH} in (NAAMM welded grating cross bars); check: our '
                 f'bars weigh {wt:.1f} lb vs the SDS/2 piece weight {pt["weight_lb"]} lb ({100 * (wt / pt["weight_lb"] - 1):+.1f} %)')
        op = {'op': 'add_part', 'id': oid, 'colour': 'AMBER',
              'part': {'role': 'plate', 'ifc_class': 'IfcPlate', 'name': f"MISC #{s['member']} / {s['name']} (piece {s['piece']}, inst {s['inst']}) bar grating",
                       'designation': s['name'], 'part_mark': f"P{s['piece']}", 'assembly_mark': f"M{s['member']}"},
              'geometry': {'kind': 'compound', 'items': items},
              'target': {'volume_mm3': round(vol, 1), 'tol_rel': 0.01},
              'provenance': {'what': f"bar grating {s['name']} {length:.2f} x {width:.4f} x {depth:g} in: {len(bars_y)} bearing bars, "
                                     f"2 end bands, {len(cross_x)} cross bars (the piece the converter left out)",
                             'source': f"SDS/2 job: {ref} vertex records (sds2_facts.json skipped[].source_evidence.vertices, "
                                       f"placement from the member file)",
                             'basis': basis,
                             'evidence': {'confidence': 0.85, 'weight_lb_ours': round(wt, 1), 'weight_lb_sds2': pt['weight_lb']}}}
        if mp:
            op['supersedes'] = [f"missing:{mp['id']}"]
            op['resolves'] = []
        patch['ops'].append(op)
        log['estimates'].append({'kind': 'grating_from_vertex_records', 'member': s['member'], 'piece': s['piece'],
                                 'supersedes': mp and mp['id'], 'bearing_bars': len(bars_y), 'cross_bars': len(cross_x),
                                 'end_bands': 2, 'weight_lb_ours': round(wt, 1), 'weight_lb_sds2': pt['weight_lb'],
                                 'confidence': {'bar_positions_and_sizes': 0.97, 'cross_bar_depth_0.25in': 0.6, 'overall': 0.85},
                                 'basis': basis})

    # ---------------- 2. MISC #61 (outline-only plate) from #62's layout
    for gid, p in t.flagged('grating_solid_panel'):
        m = None
        for i in d['instances']:
            if i['guid'] == gid:
                m = mem.get(i['member'])
                nm = i['name']
        pat = pattern.get(nm)
        if not m or not pat:
            log['not_estimated'].append({'part_id': gid, 'category': 'grating_solid_panel', 'why': 'no recorded layout for this grating'})
            continue
        p1, p2 = np.array(m['p1_mm'], float), np.array(m['p2_mm'], float)
        X = (p2 - p1) / np.linalg.norm(p2 - p1)
        Z = np.array([0.0, 0.0, 1.0])
        Y = np.cross(Z, X)
        length = float(np.linalg.norm(p2 - p1)) / IN
        cross_x = [x for x in pat['cross_x'] if x + pat['cb_w'] < length - 0.1875 - 0.05]
        items, vol = grating_items(p1, X, Y, Z, pat['bars_y'], length, pat['width'], pat['depth'], cross_x, pat['cb_w'])
        bb = p.get('bbox')
        basis = (f"estimated: MISC #{m['member']} has the same piece name ({nm}) as MISC #{pat['member']}, whose bar layout the job "
                 f"records vertex by vertex ({len(pat['bars_y'])} bearing bars, cross bars at 4 in); that layout is laid on #{m['member']}'s "
                 f"own work line ({length:.2f} in long, the converter's outline box {bb}); the SDS/2 job stores no vertices for this "
                 f"instance")
        patch['ops'].append({'op': 'replace_part', 'id': f'est:grating:{gid}', 'part_id': gid, 'colour': 'AMBER',
                             'geometry': {'kind': 'compound', 'items': items},
                             'part': {'name': f"MISC #{m['member']} / {nm} (piece 520, inst 1) bar grating"},
                             'target': {'volume_mm3': round(vol, 1), 'tol_rel': 0.01},
                             'resolves': [{'part_id': gid, 'category': c} for c in ('grating_solid_panel', 'plate_fallback')],
                             'provenance': {'what': f'bar grating {nm} {length:.2f} in long: {len(pat["bars_y"])} bearing bars, 2 end bands, '
                                                    f'{len(cross_x)} cross bars (was a solid outline plate)',
                                            'source': f"SDS/2 member file: MISC #{m['member']} work line {m['p1_mm']} -> {m['p2_mm']}",
                                            'basis': basis, 'evidence': {'confidence': 0.8}}})
        log['estimates'].append({'kind': 'grating_same_piece_layout', 'part_id': gid, 'member': m['member'], 'length_in': round(length, 3),
                                 'bearing_bars': len(pat['bars_y']), 'cross_bars': len(cross_x), 'confidence': 0.8, 'basis': basis})

    # ---------------- 3. joists
    for gid, p in t.flagged('joist_envelope'):
        inst = next(i for i in d['instances'] if i['guid'] == gid)
        m = mem[inst['member']]
        geom, info = k_joist(m)
        basis = ('estimated: SDS/2 stores only the designation 18K3 (vendor-designed joist) and its work line; depth 18 in and the '
                 '2.5 in K-series seat depth are the SJI K-series values (SJI 100 standard specification); everything else is '
                 'judged to an SJI-listed approximate weight of 6.6 lb/ft for an 18K3: top chord 2L1-1/2x1-1/2x1/8, bottom chord '
                 '2L1-1/4x1-1/4x0.109, 1 in gap, 3/4 in round web rod zig-zag, ' + f"{info['panels']} panels of {info['half_panel_mm']:.0f} mm, "
                 '4 in seats at both ends; no joist bill or vendor drawing is in the package')
        patch['ops'].append({'op': 'replace_part', 'id': f'est:joist:{gid}', 'part_id': gid, 'colour': 'AMBER', 'geometry': geom,
                             'part': {'name': f"JOIST #{m['member']} / 18K3 open-web steel joist (estimated members)"},
                             'resolves': [{'part_id': gid, 'category': 'joist_envelope'}],
                             'provenance': {'what': f"open-web joist 18K3 {info['length_mm']:.0f} mm: 2 top-chord angles, 2 bottom-chord angles, "
                                                    f"{info['web_rods']} web rods, 2 seats (was its envelope box)",
                                            'source': f"SDS/2 member file: JOIST #{m['member']} 18K3, work line {m['p1_mm']} -> {m['p2_mm']}",
                                            'standard': 'SJI K-series (ANSI/SJI 100): 18K3 nominal depth 18 in, seat depth 2.5 in, approx. weight 6.6 plf',
                                            'basis': basis, 'evidence': dict(info, confidence=0.4)}})
        log['estimates'].append(dict({'kind': 'open_web_joist', 'part_id': gid, 'member': m['member'], 'basis': basis,
                                      'confidence': {'depth_seat_length': 0.9, 'chord_and_web_sizes': 0.35, 'overall': 0.4}}, **info))

    # ---------------- 4. member envelope -> twin's tube
    for gid, p in t.flagged('member_envelope'):
        inst = next(i for i in d['instances'] if i['guid'] == gid)
        m = mem[inst['member']]
        twin = None
        for k, m2 in sorted(mem.items()):
            if k == m['member'] or (m2.get('section') or {}).get('name') != (m.get('section') or {}).get('name'):
                continue
            d1 = np.array(m['p2_mm']) - np.array(m['p1_mm'])
            d2 = np.array(m2['p2_mm']) - np.array(m2['p1_mm'])
            if np.allclose(d1, d2, atol=0.5) and abs(m['p1_mm'][2] - m2['p1_mm'][2]) < 0.5 and m['roll'] == m2['roll'] and m2['type'] == m['type']:
                tube = [i for i in d['instances'] if i.get('member') == k and i.get('kind') == 'rolled']
                if tube and t.exact(tube[0]['guid']):
                    twin = (k, m2, tube[0])
                    break
        if not twin:
            log['not_estimated'].append({'part_id': gid, 'category': 'member_envelope', 'why': 'no twin member with a fabricated tube'})
            continue
        k, m2, tb = twin
        sh = np.array(m['p1_mm']) - np.array(m2['p1_mm'])
        ex = t.exact(tb['guid'])
        sols = [{'faces': [[[[float(c) + float(sh[j]) for j, c in enumerate(pt)] for pt in loop] for loop in face] for face in so['faces']],
                 'voids': so.get('voids') or []} for so in ex['solids']]
        others = [f"#{kk}" for kk, mm in sorted(mem.items()) if (mm.get('section') or {}).get('name') == m['section']['name']
                  and mm['type'] == 'BEAM' and abs(np.linalg.norm(np.array(mm['p2_mm']) - np.array(mm['p1_mm'])) - 2133.6) < 0.5]
        basis = (f"estimated: BEAM #{m['member']} has no fabricated pieces in the SDS/2 job (only its work line); its twin BEAM #{k} "
                 f"has the same section, length, direction, elevation and roll, and its tube (piece {tb['piece']}) runs 76.2 mm in from "
                 f"each work point like every HSS5x5x1/4 beam of this length ({', '.join(others)}); that tube is moved by "
                 f"{[round(x, 2) for x in sh.tolist()]} mm onto #{m['member']}'s work line; end connections of #{m['member']} are not "
                 f"recorded and not added")
        patch['ops'].append({'op': 'replace_part', 'id': f'est:twin:{gid}', 'part_id': gid, 'colour': 'AMBER',
                             'geometry': {'kind': 'faceted', 'solids': sols},
                             'part': {'name': f"BEAM #{m['member']} / HSS5x5x1/4 (tube as twin BEAM #{k} piece {tb['piece']})"},
                             'resolves': [{'part_id': gid, 'category': 'member_envelope'}],
                             'provenance': {'what': f"HSS5x5x1/4 tube 1981.2 mm (was the 2133.6 mm work-line envelope)",
                                            'source': f"SDS/2 job: BEAM #{k} piece {tb['piece']} faceted geometry; BEAM #{m['member']} work line",
                                            'basis': basis, 'evidence': {'confidence': 0.75, 'twin_part': tb['guid'], 'shift_mm': sh.tolist()}}})
        log['estimates'].append({'kind': 'twin_member', 'part_id': gid, 'member': m['member'], 'twin_member': k, 'twin_part': tb['guid'],
                                 'shift_mm': sh.tolist(), 'confidence': 0.75, 'basis': basis})

    # ---------------- 5. concrete prism kept
    for gid, p in t.flagged('concrete_prism'):
        patch['ops'].append({'op': 'set_fields', 'id': f'est:concrete:{gid}', 'part_id': gid, 'fields': {}, 'colour': 'AMBER',
                             'resolves': [{'part_id': gid, 'category': 'concrete_prism'}],
                             'provenance': {'what': 'concrete pour "Conc. 1.5 yards" kept as its L x W x T prism (10.08 m x 368 mm x 305 mm)',
                                            'source': 'SDS/2 job: MISC #30 piece 179 (quantity 1.5 yd3, L x W x T)',
                                            'basis': 'estimated: the job records the pour only as a quantity and a box; no drawing in the '
                                                     'package shows its shape; the prism holds the SDS/2 volume (judged, confidence 0.5)',
                                            'evidence': {'confidence': 0.5}}})
        log['estimates'].append({'kind': 'concrete_prism_kept', 'part_id': gid, 'confidence': 0.5})
    log['left_to_other_tracks'] = ['bolt_from_hole_stack (143): the SDS/2 job has f32 bolt records for most of them (gap D8) = '
                                   'track sds2_ifc (GREEN), head / nut / washer sizes = track standards (BLUE); not estimated here']
    return t, patch, log


def k_joist(m):
    p1, p2 = np.array(m['p1_mm'], float), np.array(m['p2_mm'], float)
    X = (p2 - p1) / np.linalg.norm(p2 - p1)
    Z = np.array([0.0, 0.0, 1.0])
    Y = np.cross(Z, X)
    Lj = float(np.linalg.norm(p2 - p1))
    top = p1                      # work line = top of the top chord (the envelope's top face)
    D = 18 * IN
    gap = 1.0 * IN
    tc_a, tc_t = 1.5 * IN, 0.125 * IN
    bc_a, bc_t = 1.25 * IN, 0.109 * IN
    rod_r = 0.375 * IN
    seat_d, seat_len = 2.5 * IN, 4.0 * IN
    W = lambda s, y, z: (top + X * s + Y * y + Z * z)
    items = []
    # top chord: 2 angles, horizontal leg at the top pointing out, vertical leg down along the gap
    for sg in (1, -1):
        heel = W(0, sg * gap / 2, 0).tolist()
        sec = E.L_section_world(heel, (Y * sg).tolist(), (-Z).tolist(), tc_a, tc_a, tc_t)
        items.append({'kind': 'prism', 'outline_world': [E.r6(q) for q in sec], 'normal': E.r6(X.tolist()), 'thickness': round(Lj, 6)})
    # panels
    s_e = seat_len
    n = max(2, 2 * int(round((Lj - 2 * s_e) / (24 * IN))))
    h = (Lj - 2 * s_e) / n
    zt = -0.42 * IN                    # top chord centroid below the top
    zb = -D + 0.36 * IN                # bottom chord centroid above the bottom
    b0, b1 = s_e + h, Lj - s_e - h
    for sg in (1, -1):
        heel = W(b0, sg * gap / 2, -D).tolist()
        sec = E.L_section_world(heel, (Y * sg).tolist(), Z.tolist(), bc_a, bc_a, bc_t)
        items.append({'kind': 'prism', 'outline_world': [E.r6(q) for q in sec], 'normal': E.r6(X.tolist()), 'thickness': round(b1 - b0, 6)})
    rods = 0
    for k in range(n):
        s0, s1 = s_e + k * h, s_e + (k + 1) * h
        za, zb_ = (zt, zb) if k % 2 == 0 else (zb, zt)
        items.append({'kind': 'cylinder', 'start': E.r6(W(s0, 0, za).tolist()), 'end': E.r6(W(s1, 0, zb_).tolist()), 'radius': rod_r})
        rods += 1
    # seats: 2 angles under each top-chord end, bearing leg at the seat depth
    for s0 in (0.0, Lj - seat_len):
        for sg in (1, -1):
            heel = W(s0, sg * gap / 2, -seat_d).tolist()
            sec = E.L_section_world(heel, (Y * sg).tolist(), Z.tolist(), 1.5 * IN, seat_d - tc_a - 1.0, 0.1875 * IN)
            items.append({'kind': 'prism', 'outline_world': [E.r6(q) for q in sec], 'normal': E.r6(X.tolist()), 'thickness': round(seat_len, 6)})
    area_tc = 2 * tc_t * (2 * tc_a - tc_t)
    area_bc = 2 * bc_t * (2 * bc_a - bc_t)
    rod_len = n * math.hypot(h, (zt - zb))
    vol = area_tc * Lj + area_bc * (b1 - b0) + math.pi * rod_r ** 2 * rod_len
    plf = vol / (IN ** 3) * E.STEEL_LB_PER_IN3 / (Lj / IN / 12)
    info = {'length_mm': round(Lj, 2), 'panels': n, 'half_panel_mm': round(h, 2), 'web_rods': rods,
            'weight_plf_ours_excl_seats': round(plf, 2), 'sji_approx_weight_plf_18K3': 6.6}
    return {'kind': 'compound', 'items': items}, info
