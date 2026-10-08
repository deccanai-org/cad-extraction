"""DB1 slotted bolt groups whose holes the converter cut ROUND because it could not decide which plies Tekla slots.
The slot SIZE (slot_x / slot_y) is stored in the DB1 group; WHICH plies are slotted is the estimate (AMBER):
  rule 'v2_mask'   (engines with a decoded 'slotted parts' selection, e.g. 7.82): Tekla's per-ply selection bits applied to
                   the plies ranked head-first along the bolt axis = db1step code-v rule; measured against Tekla NC1 per-part
                   hole data on 193 archives (z3conv db1step.py comment, code v): 7.82 5851/5988 = 97.7 %
  rule 'family'    (old engines, no selection decoded, e.g. 6.87): slot the connection material (plates, angles) and keep the
                   rolled members (W / C / HSS) round - measured on this project's own NC1 files (fab/nc1 of the perfect package)
The ply intervals along the bolt axis come from the baseline's own hole tools (the converter's hole plan HP: tool = bolt
point + ez*(z0-2) .. z1+2), so no geometry is re-derived."""
import collections
import math
import re

import est_common as E

FAMILY_ROUND = ('W', 'C', 'MC', 'HSS', 'HP', 'S', 'WT', 'PIPE', 'TS')


def fam(profile):
    m = re.match(r'^([A-Z]+)', (profile or '').upper())
    return m.group(1) if m else '?'


def ply_intervals(tree, gid, P, ez):
    """hole tools of part gid whose axis passes through bolt point P along ez -> [(t0, t1, tool row, dh)]"""
    out = []
    for r in tree.by_part.get(gid, []):
        if r['role'] != 'cut_tool':
            continue
        o, x, z, v = E.solid_frame(r)
        L = E.norm(v)
        if L <= 0:
            continue
        u = E.unit(v)
        if abs(E.dot(u, ez)) < 0.999:
            continue
        w = E.sub(P, o)
        off = E.norm(E.sub(w, E.mul(u, E.dot(w, u))))
        if off > 0.75:
            continue
        a = E.dot(E.sub(o, P), ez)
        b = E.dot(E.sub(E.add(o, v), P), ez)
        prof = tree.profiles.get(r['profile_id']) or {}
        if prof.get('kind') != 'CIRCLE':
            continue
        dh = 2.0 * float(prof['radius'])
        out.append((min(a, b) + 2.0, max(a, b) - 2.0, r, dh))
    return out


def nc1_family_stats(nc1_dir):
    """this project's NC1 parts: per profile family, parts with holes / parts with slotted holes (DSTV BO 'l' flag)"""
    import glob
    holes, slots = collections.Counter(), collections.Counter()
    sizes = collections.Counter()
    files = sorted(glob.glob(nc1_dir + '/*.nc1'))
    for f in files:
        L = open(f, errors='replace').read().splitlines()
        i = 0
        while i < len(L) and L[i].strip() != 'ST':
            i += 1
        hdr = []
        i += 1
        while i < len(L) and L[i].strip() not in ('BO', 'AK', 'IK', 'SI', 'KO', 'PU', 'KA', 'EN', 'BR'):
            if not L[i].strip().startswith('**'):
                hdr.append(L[i].strip())
            i += 1
        cur, bo = None, []
        for s in L[i:]:
            t = s.strip()
            if t in ('BO', 'AK', 'IK', 'SI', 'KO', 'PU', 'KA', 'EN', 'BR'):
                cur = t
                continue
            if cur == 'BO':
                bo.append(t)
        prof = hdr[5] if len(hdr) > 5 else ''
        if not bo:
            continue
        fm = fam(prof)
        holes[fm] += 1
        sl = [h for h in bo if re.search(r'\dl\s', h + ' ')]
        if sl:
            slots[fm] += 1
            for h in sl:
                p = h.split()
                if len(p) >= 7:
                    sizes[(p[3], p[5], p[6])] += 1
    return {'files': len(files), 'parts_with_holes': dict(holes), 'parts_with_slots': dict(slots),
            'slot_sizes_d_dx_dy': {' '.join(k): v for k, v in sizes.most_common()}}


def estimate(tree, sk, patch, log, rule, nc1=None, engine_acc=None, extra_ply_owner=None, db1_groups=None):
    """sk = src_db1 skipped_records.json. rule 'v2_mask' | 'family'. extra_ply_owner(group, P) -> op id of a part
    another estimate adds that takes this group's slot (n2 tread carriers), or None. db1_groups = the db1 track's
    decoded slot groups (restoration_log.json slot_groups): a group it decodes from the DB1 is ITS op (GREEN); we emit
    no op for it and record whether our estimate agrees with its decode (a measured check of the estimate rule)."""
    prof_of = {p[0]: p[1] for p in sk['parts']}
    flagged_plies = {gid for gid, _ in tree.flagged('slotted_ply_round_holes')}
    flagged_groups = {gid for gid, _ in tree.flagged('slotted_holes_round')}
    done_plies, done_groups = set(), set()
    stats = collections.Counter()
    for g in sk['bolt_groups']:
        if not str(g['slot'].get('decision', '')).startswith('undecided'):
            continue
        s = g['slot']
        if 'slot' in s:
            sx, sy = abs(float(s['slot'][0] or 0)), abs(float(s['slot'][1] or 0))
        else:
            sx, sy = abs(float(s.get('slot_x') or 0)), abs(float(s.get('slot_y') or 0))
        ez = E.unit(E.V(g['z'] if 'z' in g else g['bolts'][0]['axis']))
        Ps = [E.V(p) for p in g['positions_world']]
        # group x axis: decoded (new engines) or the bolt line (old engines; on n1 64/64 straight multi-bolt groups run
        # from the first to the last bolt along +x)
        if 'x' in g:
            ex, ex_basis = E.unit(E.V(g['x'])), 'decoded group x axis (DB1 record)'
            ex_conf = 1.0
        elif len(Ps) > 1:
            d = E.sub(Ps[-1], Ps[0])
            d = E.sub(d, E.mul(ez, E.dot(d, ez)))
            ex, ex_basis = E.unit(d), ('group x axis not exported for this engine: taken along the bolt line, first to last '
                                       'bolt (on n1, engine 7.82, 64 of 64 straight multi-bolt groups have x along that line)')
            ex_conf = 0.9
        else:
            ex, ex_basis, ex_conf = None, None, 0.5
        plies = [p for p in g['plies'] if p.get('written')]
        iv, tools = {}, {}
        for p in plies:
            pid = p['gid']
            rows = []
            for P in Ps:
                hits = ply_intervals(tree, pid, P, ez)
                if hits:
                    rows.append((P, hits[0]))
            if rows:
                iv[pid] = (sum(h[0] for _, h in rows) / len(rows), sum(h[1] for _, h in rows) / len(rows))
                tools[pid] = rows
        ops_before = len(patch['ops'])
        entry = {'kind': 'slotted_ply_selection', 'group_record': g['record'], 'group_part_id': g.get('gid'),
                 'slot_mm': {'x': sx, 'y': sy}, 'bolts': len(Ps), 'plies': [], 'rule': rule}
        decision = {}
        why = None
        if rule == 'v2_mask':
            mk = s.get('slot_parts_mask')
            rot = s.get('rotate_slots') or 0
            n = len(plies)
            full = (1 << min(n, 5)) - 1
            if mk is None or len(iv) < n:
                why = 'ply not located on the bolt axis' if mk is not None else 'no selection mask'
            elif rot not in (0, 1, 2):
                why = 'rotate-slots value unknown'
            else:
                od = sorted(iv, key=lambda q: -(iv[q][0] + iv[q][1]))
                if any(iv[od[k + 1]][1] > iv[od[k]][0] + 1.0 for k in range(n - 1)):
                    why = 'overlapping plies'
                else:
                    for k, q in enumerate(od):
                        rot_q = (rot == 1 and k % 2 == 1) or (rot == 2 and k % 2 == 0)
                        decision[q] = (bool(k < 5 and (mk >> k) & 1), rot_q, k + 1)
                    entry['selection_mask'] = mk
                    entry['mask_bits_head_first'] = format(mk & full, f'0{min(n, 5)}b')[::-1]
                    entry['rotate_slots'] = rot
            conf = engine_acc['rate'] if engine_acc else 0.9
            basis_rule = (f"Tekla 'slotted parts' selection bits of the DB1 group (mask {mk}) applied to the plies ranked from the bolt "
                          f"head along the bolt axis (db1step rule v2, the converter's own code, switched off for engine {sk.get('engine')} "
                          f"only because it misses 99 %); measured against Tekla NC1 per-part holes on 193 archives: engine "
                          f"{sk.get('engine')} {engine_acc['agree']}/{engine_acc['n']} = {100 * engine_acc['rate']:.1f} %"
                          if engine_acc else 'Tekla slotted-parts mask, plies ranked head first')
        else:
            fams = {q: fam(prof_of.get(next((p['record'] for p in plies if p['gid'] == q), None))) for q in iv}
            conn = [q for q in iv if fams[q] not in FAMILY_ROUND]
            if len(iv) < len(plies):
                why = 'ply not located on the bolt axis'
            elif not conn:
                why = 'no plate / angle ply in this model: the slotted ply is outside the model'
            else:
                for q in iv:
                    decision[q] = (q in conn, False, None)
            h, sl = (nc1 or {}).get('parts_with_holes', {}), (nc1 or {}).get('parts_with_slots', {})
            rolled = sum(h.get(f, 0) for f in FAMILY_ROUND)
            rolled_sl = sum(sl.get(f, 0) for f in FAMILY_ROUND)
            pl_h, pl_s = h.get('PL', 0) + h.get('FL', 0), sl.get('PL', 0) + sl.get('FL', 0)
            l_h, l_s = h.get('L', 0), sl.get('L', 0)
            basis_rule = (f"slotted holes go in the connection material, not in the rolled member: this project's own NC1 files "
                          f"({(nc1 or {}).get('files')} parts, fab/nc1 of the perfect package) show slotted holes in "
                          f"{rolled_sl}/{rolled} W/C/HSS parts with holes, {pl_s}/{pl_h} plates and {l_s}/{l_h} angles; "
                          f"engine {sk.get('engine')} stores the slot size but no decoded ply selection")
            conf = 0.8
        if why:
            entry['decision'] = 'not_estimated'
            entry['why'] = why
            owner = extra_ply_owner(g, Ps) if extra_ply_owner else None
            if owner:
                entry['decision'] = 'slot_in_added_part'
                entry['why'] = why + f'; the slot is cut in the estimated part {owner}'
            stats['groups_' + entry['decision']] += 1
            log['estimates' if owner else 'not_estimated'].append(entry)
            if owner:
                for q in iv:
                    done_plies.add(q)
                    patch['ops'].append({'op': 'set_fields', 'id': f'est:slot:{g["record"]}:{q}', 'part_id': q, 'fields': {},
                                         'colour': 'AMBER', 'resolves': [{'part_id': q, 'category': 'slotted_ply_round_holes'}],
                                         'provenance': {'what': f'bolt holes kept ROUND in this {fams_or(prof_of, plies, q)} (bolt group {g["record"]}): '
                                                                f'the slotted ply of this group is the estimated part {owner}',
                                                        'source': f'DB1 bolt group record {g["record"]}: slot {sx:g} x {sy:g} mm',
                                                        'basis': 'estimated: ' + basis_rule,
                                                        'evidence': {'confidence': round(conf, 3)}}})
                if g.get('gid') in flagged_groups:
                    done_groups.add(g['gid'])
                    patch['ops'].append(group_op(g, sx, sy, owner_note=owner, basis=basis_rule, conf=conf))
            continue
        nslot = 0
        for q in iv:
            sl, rot_q, rank = decision[q]
            dh_all = [h[3] for _, h in tools[q]]
            sx_q, sy_q = (sy, sx) if rot_q else (sx, sy)
            ply = {'part_id': q, 'profile': prof_of.get(next((p['record'] for p in plies if p['gid'] == q), None)),
                   'rank_from_head': rank, 'interval_along_axis_mm': [round(iv[q][0], 2), round(iv[q][1], 2)],
                   'slotted': sl, 'rotated': rot_q, 'holes': len(tools[q])}
            entry['plies'].append(ply)
            conf_q = conf if ex is not None or not sl else min(conf, ex_conf)
            if sl and ex is None:
                # single-bolt old-engine group: slot direction from the ply's long in-plane axis (estimated)
                exq, exb = long_axis(tree, q, ez)
                ply['slot_x_axis_basis'] = exb
            else:
                exq, exb = ex, ex_basis
            if sl:
                nslot += 1
                rm, cuts = [], []
                for P, (t0, t1, row, dh) in tools[q]:
                    c = tree.cuts_by_tool.get(row['solid_id'])
                    if not c:
                        continue
                    rm.append(c['cut_id'])
                    o, x, z, v = E.solid_frame(row)
                    cuts.append({'kind': 'solid', 'tool': E.slot_tool(o, v, exq, dh, sx_q, sy_q)})
                ply['removed_round_cuts'] = rm
                ply['slot_tools'] = [{'centre': E.r6(P), 'd_mm': round(dh, 3), 'long_mm': round(dh + max(sx_q, sy_q), 3),
                                      'along': 'group x' if sx_q >= sy_q else 'group y'} for P, (_, _, _, dh) in tools[q]]
                ply['confidence'] = round(conf_q, 3)
                patch['ops'].append({
                    'op': 'replace_cuts', 'id': f'est:slot:{g["record"]}:{q}', 'part_id': q, 'remove_cut_ids': rm,
                    'remove_opening_ids': [], 'cuts': cuts, 'colour': 'AMBER',
                    'resolves': [{'part_id': q, 'category': 'slotted_ply_round_holes'}],
                    'provenance': {
                        'what': f'{len(cuts)} round bolt hole(s) replaced by slotted holes {dh_all[0]:g} x {dh_all[0] + max(sx_q, sy_q):g} mm '
                                f'(bolt group {g["record"]}, ply {rank or "-"} from the head)',
                        'source': f'DB1 bolt group record {g["record"]}: slot {sx:g} mm along x, {sy:g} mm along y; hole d {dh_all[0]:g} mm',
                        'basis': f'estimated: which ply is slotted - {basis_rule}; slot direction: {exb}',
                        'evidence': {'confidence': round(conf_q, 3), 'rule': rule, 'group_record': g['record']}}})
            else:
                ply['confidence'] = round(conf, 3)
                patch['ops'].append({
                    'op': 'set_fields', 'id': f'est:slot:{g["record"]}:{q}', 'part_id': q, 'fields': {}, 'colour': 'AMBER',
                    'resolves': [{'part_id': q, 'category': 'slotted_ply_round_holes'}],
                    'provenance': {'what': f'bolt holes of group {g["record"]} kept ROUND in this ply (estimated not slotted)',
                                   'source': f'DB1 bolt group record {g["record"]}: slot {sx:g} x {sy:g} mm',
                                   'basis': f'estimated: {basis_rule}',
                                   'evidence': {'confidence': round(conf, 3), 'rule': rule}}})
            done_plies.add(q)
        entry['decision'] = 'estimated'
        entry['plies_slotted'] = nslot
        entry['confidence'] = round(conf, 3)
        entry['basis'] = basis_rule
        entry['slot_x_axis'] = ex_basis
        log['estimates'].append(entry)
        stats['groups_estimated'] += 1
        stats['plies_slotted'] += nslot
        stats['plies_round'] += len(iv) - nslot
        if g.get('gid') in flagged_groups:
            done_groups.add(g['gid'])
            patch['ops'].append(group_op(g, sx, sy, basis=basis_rule, conf=conf, nslot=nslot))
    if db1_groups:
        # the db1 track decodes these groups' slotted-ply selection from the DB1 (GREEN): our ops for them are withdrawn
        # (applied after db1 they would overwrite its exact result); our decision is kept in the log with the agreement
        cov = {str(k) for k in db1_groups}
        keep, dropped = [], collections.Counter()
        for o in patch['ops']:
            pr = o['id'].split(':')
            if pr[0] == 'est' and pr[1] in ('slot', 'slotgroup') and pr[2] in cov:
                dropped[o['op']] += 1
                continue
            keep.append(o)
        patch['ops'][:] = keep
        agree = collections.Counter()
        for e in log['estimates'] + log['not_estimated']:
            if e.get('kind') != 'slotted_ply_selection' or str(e['group_record']) not in cov:
                continue
            dg = db1_groups[str(e['group_record'])]
            theirs = set(dg.get('slotted_gid') or [])
            e['db1_track_decode'] = {'how': dg.get('how'), 'path': dg.get('path'), 'mask': dg.get('mask'), 'slotted': sorted(theirs)}
            if e['decision'] == 'estimated':
                ok = all((p['part_id'] in theirs) == p['slotted'] for p in e['plies'])
                for p in e['plies']:
                    agree['plies_agree' if (p['part_id'] in theirs) == p['slotted'] else 'plies_disagree'] += 1
            else:
                ok = not theirs           # slot outside the modelled plies: db1 decodes 'no part slotted'
                agree['groups_outside_model_agree' if ok else 'groups_outside_model_disagree'] += 1
            e['agrees_with_db1_decode'] = ok
            e['decision'] = e['decision'] + '__deferred_to_db1_track'
        stats['ops_withdrawn_for_db1_track'] = dict(dropped)
        stats['agreement_with_db1_decode'] = dict(agree)
        done_plies = set()
        done_groups = set()
    stats['flagged_plies'] = len(flagged_plies)
    stats['flagged_plies_resolved'] = len(flagged_plies & done_plies)
    stats['flagged_groups'] = len(flagged_groups)
    stats['flagged_groups_resolved'] = len(flagged_groups & done_groups)
    return dict(stats), flagged_plies - done_plies, flagged_groups - done_groups


def fams_or(prof_of, plies, q):
    return prof_of.get(next((p['record'] for p in plies if p['gid'] == q), None)) or 'ply'


def group_op(g, sx, sy, basis, conf, nslot=None, owner_note=None):
    return {'op': 'set_fields', 'id': f'est:slotgroup:{g["record"]}', 'part_id': g['gid'], 'fields': {}, 'colour': 'AMBER',
            'resolves': [{'part_id': g['gid'], 'category': 'slotted_holes_round'}],
            'provenance': {'what': f'bolt group {g["record"]}: slotted holes ({sx:g} x {sy:g} mm) now cut in the estimated plies'
                                   + (f' ({nslot} slotted)' if nslot is not None else f' (in {owner_note})') + '; the bolts are unchanged',
                           'source': f'DB1 bolt group record {g["record"]}',
                           'basis': f'estimated: {basis}', 'evidence': {'confidence': round(conf, 3)}}}


def long_axis(tree, pid, ez):
    """the longest in-plane direction (square to the bolt axis) of a part's body solids: its extrusion or its section x"""
    best, bl = None, -1.0
    for r in tree.by_part.get(pid, []):
        if r['role'] != 'body':
            continue
        o, x, z, v = E.solid_frame(r)
        for d in (v, x):
            d2 = E.sub(d, E.mul(ez, E.dot(d, ez)))
            if E.norm(d2) > bl and E.norm(d2) > 1e-6:
                bl, best = E.norm(d2), E.unit(d2)
    return best, ('estimated: single-bolt group, the group x axis is not exported for this engine: the slot is taken along the '
                  'ply\'s long in-plane axis (judged, confidence 0.5)')
