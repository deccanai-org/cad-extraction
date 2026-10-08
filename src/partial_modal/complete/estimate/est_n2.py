"""n2_db1_addon (F232-MASTER, DB1 engine 6.87): AMBER estimates
  1. stair treads GRTG279.4*25.4 (34): the converter wrote a solid RECT plate standing on edge (the GRTG numbers taken as
     plate thickness x width). Estimated: a welded bar-grating stair tread lying flat (11 in deep = the stair run, 1 in thick)
     with 1/4 in end carrier plates carrying the stringer bolts, 1 x 3/16 in bearing bars at 1-3/16 in and 1/4 in cross
     bars at 4 in (19-W-4, the NAAMM default type; the tread's type is not recorded).
  2. slotted plies of the old-engine slotted groups (est_slots, rule 'family'); groups whose only modelled ply is the
     stringer get their slot in the estimated tread carrier.
  3. washer 2 side (5 bolts), polybeam corners (30 bent RB25.4): the converter's inference kept, labelled AMBER."""
import json
import math
import os

import est_common as E
import est_slots

T_IN = 25.4
TC = 6.35            # carrier plate 1/4 in
HC = 76.2            # carrier plate 3 in deep
BB_T = 4.7625        # bearing bar 3/16 in
BB_P = 30.1625       # bearing bar pitch 1-3/16 in (19-W-4)
CB = 6.35            # cross bar 1/4 in square
CB_P = 101.6         # cross bar pitch 4 in


def tread_frames(t):
    out = {}
    for gid, p in t.flagged('grating_solid_plate'):
        rows = [r for r in t.by_part.get(gid, []) if r['role'] == 'body']
        if len(rows) != 1:
            continue
        r = rows[0]
        prof = t.profiles[r['profile_id']]
        o, x, z, v = E.solid_frame(r)
        L = E.norm(v)
        u = E.unit(v)
        b, d = float(prof['b']), float(prof['d'])
        if abs(abs(x[2]) - 1.0) > 1e-6:
            out[gid] = None
            continue
        up = [0.0, 0.0, 1.0]
        w = E.unit(E.cross(up, u))          # horizontal, square to the tread length
        out[gid] = {'o': o, 'u': u, 'w': w, 'up': up, 'L': L, 'D': b, 'T': d, 'x': x, 'row': r}
    return out


def carrier_boxes(fr):
    """the two end carrier plates of a tread, as (origin corner, axes, sizes) boxes in world"""
    o, u, w, up, L, D, T = fr['o'], fr['u'], fr['w'], fr['up'], fr['L'], fr['D'], fr['T']
    top = E.add(o, E.mul(up, T / 2))
    out = []
    for s0 in (0.0, L - TC):
        corner = E.add(E.add(top, E.mul(u, s0)), E.add(E.mul(w, -D / 2), E.mul(up, -HC)))
        out.append((corner, s0))
    return out


def in_carrier(fr, P, slack=12.0):
    o, u, w, up, L, D, T = fr['o'], fr['u'], fr['w'], fr['up'], fr['L'], fr['D'], fr['T']
    d = E.sub(P, o)
    s, q, h = E.dot(d, u), E.dot(d, w), E.dot(d, up)
    if not (-D / 2 + 10 < q < D / 2 - 10 and T / 2 - HC + 10 < h < T / 2):
        return None
    if -slack <= s <= TC + slack:
        return 0
    if L - TC - slack <= s <= L + slack:
        return 1
    return None


def tread_geom(fr, holes):
    """compound: 2 carriers (with their bolt holes), bearing bars, cross bars"""
    o, u, w, up, L, D, T = fr['o'], fr['u'], fr['w'], fr['up'], fr['L'], fr['D'], fr['T']
    top = E.add(o, E.mul(up, T / 2))
    P = lambda s, q, h: E.add(top, E.add(E.mul(u, s), E.add(E.mul(w, q), E.mul(up, h))))
    items = []
    for k, s0 in enumerate((0.0, L - TC)):
        outline = [E.r6(P(s0, -D / 2, 0)), E.r6(P(s0, D / 2, 0)), E.r6(P(s0, D / 2, -HC)), E.r6(P(s0, -D / 2, -HC))]
        g = {'kind': 'prism', 'outline_world': outline, 'normal': E.r6(u), 'thickness': TC}
        cuts = [h['cut'] for h in holes if h['end'] == k]
        if cuts:
            g['cuts'] = cuts
        items.append(g)
    n = int(math.floor((D - BB_T) / BB_P)) + 1
    q0 = -(BB_P * (n - 1)) / 2
    for i in range(n):
        q = q0 + i * BB_P
        outline = [E.r6(P(TC, q - BB_T / 2, 0)), E.r6(P(TC, q + BB_T / 2, 0)), E.r6(P(TC, q + BB_T / 2, -T)),
                   E.r6(P(TC, q - BB_T / 2, -T))]
        items.append({'kind': 'prism', 'outline_world': outline, 'normal': E.r6(u), 'thickness': L - 2 * TC})
    span = L - 2 * TC
    m = max(1, int(math.floor(span / CB_P)))
    s0 = TC + (span - (m - 1) * CB_P) / 2
    for j in range(m):
        s = s0 + j * CB_P
        outline = [E.r6(P(s - CB / 2, -D / 2 + BB_T, 0)), E.r6(P(s + CB / 2, -D / 2 + BB_T, 0)),
                   E.r6(P(s + CB / 2, -D / 2 + BB_T, -CB)), E.r6(P(s - CB / 2, -D / 2 + BB_T, -CB))]
        items.append({'kind': 'prism', 'outline_world': outline, 'normal': E.r6(w), 'thickness': D - 2 * BB_T})
    vol = 2 * TC * D * HC + n * BB_T * T * (L - 2 * TC) + m * CB * CB * (D - 2 * BB_T)
    return {'kind': 'compound', 'items': items}, n, m, vol


def make(tag, engine_acc=None, db1_groups=None, db1_parts=None):
    t = E.Tree(tag)
    skp = os.path.join(E.INPUTS, 'n2', 'skipped_records.json')
    t.add_input(skp)
    sk = json.load(open(skp))
    patch, log = E.new_patch(t), E.new_log(t)
    nc1 = est_slots.nc1_family_stats(os.path.join(E.INPUTS, 'n2', 'nc1'))
    log['nc1_project_stats'] = dict(nc1, where='dataset/packages/3d/<pid>/fab/nc1 (perfect package of the same project, 837 files)')

    # ---------------- treads
    frames = tread_frames(t)
    tread_ops = {}
    holes_by = {gid: [] for gid in frames}
    group_owner = {}
    for g in sk['bolt_groups']:
        Ps = [E.V(p) for p in g['positions_world']]
        for gid, fr in frames.items():
            if fr is None:
                continue
            ends = [in_carrier(fr, P) for P in Ps]
            if all(e is not None for e in ends):
                group_owner[g['record']] = gid
                s = g['slot']
                sl = s.get('slot') or [0, 0]
                slotted = str(s.get('decision', '')).startswith('undecided') and (sl[0] or sl[1])
                ez = E.unit(E.V(g['bolts'][0]['axis']))
                if len(Ps) > 1:
                    dd = E.sub(Ps[-1], Ps[0])
                    ex = E.unit(E.sub(dd, E.mul(ez, E.dot(dd, ez))))
                else:
                    ex = fr['w']
                for P, e in zip(Ps, ends):
                    # hole diameter = the stringer's own hole of this bolt (same group), else d + the group tolerance
                    dh = None
                    for p in g['plies']:
                        hits = est_slots.ply_intervals(t, p['gid'], P, ez)
                        if hits:
                            dh = hits[0][3]
                            break
                    if dh is None:
                        dh = float(g['d']) + float(g['bolts'][0].get('tolerance') or 1.59)
                    s0 = 0.0 if e == 0 else fr['L'] - TC
                    d = E.sub(P, fr['o'])
                    base = E.add(fr['o'], E.add(E.mul(fr['w'], E.dot(d, fr['w'])), E.mul(fr['up'], E.dot(d, fr['up']))))
                    org = E.add(base, E.mul(fr['u'], s0 - 2.0))
                    vecu = E.mul(fr['u'], TC + 4.0)
                    if slotted:
                        tool = E.slot_tool(org, vecu, ex, dh, abs(sl[0]), abs(sl[1]))
                    else:
                        tool = {'kind': 'cylinder', 'start': E.r6(org), 'end': E.r6(E.add(org, vecu)), 'radius': round(dh / 2, 6)}
                    holes_by[gid].append({'end': e, 'cut': {'kind': 'solid', 'tool': tool}, 'group': g['record'],
                                          'slotted': bool(slotted), 'dh': dh})
                break
    nb = 0
    for gid in sorted(frames):
        fr = frames[gid]
        if fr is None:
            log['not_estimated'].append({'part_id': gid, 'category': 'grating_solid_plate', 'why': 'section x not vertical: not a stair tread'})
            continue
        geom, n, m, vol = tread_geom(fr, holes_by[gid])
        oid = f'est:tread:{gid}'
        tread_ops[gid] = oid
        hs = holes_by[gid]
        basis = ('estimated: the GRTG279.4*25.4 parts are stair treads - consecutive ones step 279.4 mm along the run and 192 mm up '
                 '(11 in run = the 279.4 number, so the 279.4 side lies flat and the 25.4 side is the thickness; the converter stood '
                 'the plate on edge); each end sits on a C10X15.3 stringer whose bolt pairs (7 in apart, along the run, 31.8 mm below '
                 'the tread centre) fall inside a 1/4 in end carrier plate, which we add with those holes; the bar layout is not '
                 'recorded: 19-W-4 (bearing bars 1 x 3/16 in at 1-3/16 in, cross bars 1/4 in at 4 in) is assumed, the NAAMM MBG 531 '
                 'default welded-steel type; nosing and carrier size (1/4 x 3 in) judged')
        patch['ops'].append({
            'op': 'replace_part', 'id': oid, 'part_id': gid, 'geometry': geom, 'colour': 'AMBER',
            'part': {'name': f'STAIR TREAD GRTG 11 x 1 in x {fr["L"] / E.IN:g} in (19-W-4 bar grating, estimated)', 'role': 'plate'},
            'resolves': [{'part_id': gid, 'category': 'grating_solid_plate'}],
            'target': {'volume_mm3': round(vol, 1), 'tol_rel': 0.01},
            'provenance': {'what': f'bar-grating stair tread {fr["L"]:.1f} mm long, 279.4 mm deep, 25.4 mm thick: 2 end carrier plates '
                                   f'({len(hs)} bolt holes, {sum(1 for h in hs if h["slotted"])} slotted), {n} bearing bars, {m} cross bars',
                           'source': 'DB1 part: profile string GRTG279.4*25.4, its axis and length (solids.csv); DB1 bolt groups '
                                     + ', '.join(sorted({str(h['group']) for h in hs})) + ' (positions, hole d, slot size)',
                           'standard': 'NAAMM MBG 531 welded steel grating 19-W-4: bearing bars at 1-3/16 in, cross bars at 4 in (type assumed)',
                           'basis': basis,
                           'evidence': {'confidence': 0.6, 'bearing_bars': n, 'cross_bars': m, 'carrier_holes': len(hs)}}})
        log['estimates'].append({'kind': 'stair_tread', 'part_id': gid, 'length_mm': round(fr['L'], 2), 'depth_mm': fr['D'],
                                 'thickness_mm': fr['T'], 'bearing_bars': n, 'cross_bars': m,
                                 'carrier_holes': [{'group': h['group'], 'end': h['end'], 'slotted': h['slotted'], 'd': round(h['dh'], 3)} for h in hs],
                                 'confidence': {'lies_flat_11in_run': 0.95, 'carrier_plates_and_holes': 0.7, 'bar_layout_19W4': 0.5,
                                                'overall': 0.6},
                                 'basis': basis})
        nb += 1
    log['summary']['treads'] = nb

    def owner(g, Ps):
        gid = group_owner.get(g['record'])
        return tread_ops.get(gid) and f'{tread_ops[gid]} (end carrier plate of tread {gid})'

    st, left_p, left_g = est_slots.estimate(t, sk, patch, log, 'family', nc1=nc1, extra_ply_owner=owner, db1_groups=db1_groups)
    log['summary']['slotted_plies'] = st
    if not db1_groups:
        for q in sorted(left_p):
            log['not_estimated'].append({'part_id': q, 'category': 'slotted_ply_round_holes', 'why': 'see not_estimated group entries'})
        for q in sorted(left_g):
            log['not_estimated'].append({'part_id': q, 'category': 'slotted_holes_round', 'why': 'see not_estimated group entries'})

    # ---------------- washer 2 side
    for gid, p in t.flagged('washer_side_inferred'):
        patch['ops'].append({'op': 'set_fields', 'id': f'est:washer2:{gid}', 'part_id': gid, 'fields': {}, 'colour': 'AMBER',
                             'resolves': [{'part_id': gid, 'category': 'washer_side_inferred'}],
                             'provenance': {'what': 'second washer kept under the nut, as the converter placed it',
                                            'source': 'DB1 bolt string: assembly flags (washer 2 count = digit 3)',
                                            'basis': 'estimated: the DB1 stores how many washers, not on which side; Tekla\'s bolt '
                                                     'assembly puts washer 1 under the head and washers 2 / 3 under the nut, so the '
                                                     'digit-3 washer goes under the nut (judged, confidence 0.85)',
                                            'evidence': {'confidence': 0.85}}})
        log['estimates'].append({'kind': 'washer_side', 'part_id': gid, 'name': p['name'][:80], 'decision': 'nut side (kept)',
                                 'confidence': 0.85})
    # ---------------- polybeam corners
    db1_poly = {pid for pid, r in (db1_parts or {}).items() if any(e.get('kind') == 'polybeam_corners' for e in r.get('events', []))}
    if db1_poly:
        log['polybeam_note'] = (f'the db1 track decodes the chamfer type of every polybeam point from the DB1 ({len(db1_poly)} parts, '
                                'complete/db1/out/n2/restoration_log.json): the corners are ITS ops; ours withdrawn')
    for gid, p in t.flagged('polybeam_straight_segments'):
        if gid in db1_poly:
            continue
        other = [f['category'] for f in p['flags'] if f['category'] != 'polybeam_straight_segments']
        patch['ops'].append({'op': 'set_fields', 'id': f'est:polybeam:{gid}', 'part_id': gid, 'fields': {}, 'colour': 'AMBER',
                             'resolves': [{'part_id': gid, 'category': 'polybeam_straight_segments'}],
                             'provenance': {'what': 'bent round bar RB25.4: corners kept as mitred joints of the stored polyline',
                                            'source': 'DB1 polybeam record: polyline points',
                                            'basis': 'estimated: the bend (chamfer) fields of the polybeam points are not decoded; '
                                                     'Tekla\'s default polybeam chamfer is "none", which is the sharp mitred corner the '
                                                     'converter wrote; no drawing or NC1 of this model names a bend radius (judged, '
                                                     'confidence 0.5)',
                                            'evidence': {'confidence': 0.5, 'unresolved_here': other}}})
        log['estimates'].append({'kind': 'polybeam_corner', 'part_id': gid, 'decision': 'mitred corners kept', 'confidence': 0.5,
                                 'still_open': other})
    log['left_to_other_tracks'] = ['bolt_nominal_head_nut (34) and washers with nominal thickness (34): bolt standards = track '
                                   'standards (BLUE)', 'our_script_mismatch (28 polybeams, volume 0.76 %): a rebuild problem of the '
                                   'pipeline, not an estimate - stays MAGENTA unless fixed', 'split_in_pieces (YELLOW, 2 C10X15.3): '
                                   'as in the source']
    return t, patch, log
