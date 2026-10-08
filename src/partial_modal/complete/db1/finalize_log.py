#!/usr/bin/env python3
"""finalize_log.py RESTORATION_LOG.json BASELINE_ISSUES.json SKIPPED_RECORDS.json OUT.json

Adds the colour verdict of this track (DB1 restoration) to every part the restoration touched or verified, and resolves the
baseline issue model's ORANGE flags that belong to this track (fittings / slotted holes / polybeam corners):
  GREEN  geometry restored EXACTLY from DB1 data the shipped conversion ignored (slotted holes, Tekla fittings, despiked outlines)
  AMBER  restored from DB1 data with one inferred element (stated basis), e.g. a line cut whose removed side is not fixed by the data
  GREY   unchanged and now VERIFIED from DB1 data (fitting plane on the member end; ply the slot mask leaves round; bolt group whose
         slot decision is decoded; polybeam whose DB1 corners carry no chamfer)
Standard library only."""
import json, sys

FIT_KISS = ('cross-check: KISS 150VB HSS10X10X1/2 = 8978.90 mm, NC1 150VB.nc1 = 8978.35 mm; the restored brace '
            '(record 200075) is {L} mm long (the shipped one {L0} mm)')


def main():
    log = json.load(open(sys.argv[1])); iss = json.load(open(sys.argv[2])); sk = json.load(open(sys.argv[3])); outp = sys.argv[4]
    AX = {f['record']: f['axis'] for f in sk.get('fittings_not_applied') or []}
    eng = log.get('engine')
    v2 = {'7.64': '1246/1249', '7.82': '5851/5988', '8.07': '5943/6067', '8.44': '1970/2019', '8.53': '619/621', '8.85': '1706/1806', '9.08': '283/283'}
    old = {'6.87': '374/374 on the 7.01 record layout + six 6.87 models (45 groups cut round -> 0, 0 invalid)', '7.01': '374/374',
           '7.24': '2370/2496', '7.30': '546/546'}
    slot_val = (f'Tekla NC1 per-part agreement of this slot decode on engine {eng}: '
                + (v2.get(eng) or old.get(eng) or 'not measured'))
    parts = log['parts']
    colours = {}
    hss = [p for p in parts.values() if p.get('record') == 200075]
    for g, p in parts.items():
        kinds = [e['kind'] for e in p['events']]
        reasons = []; col = None
        if p['geometry'] == 'CHANGED_WITHOUT_EVENT':
            col = 'MAGENTA'; reasons.append('geometry changed without a restoration event (unexplained)')
        elif p['geometry'] == 'restored':
            col = 'GREEN'
            for e in p['events']:
                if e['kind'] == 'slotted_hole':
                    reasons.append(f"slotted hole restored: d {e['hole_d']} mm + slot {e['slot_x']} x {e['slot_y']} mm (bolt group {e['group']}"
                                   f"{', rotated' if e.get('rotated') else ''}) from DB1 {e['db1_field']}; {slot_val}")
                elif e['kind'] == 'fitting_applied':
                    lc = e.get('line_cuts') or []
                    txt = (f"Tekla fitting applied from DB1 ({e['db1_field']}): record length {e['L_record']} -> {e['L_fitted']} mm, "
                           f"end trims {e['end_trims_mm']}, {len(e.get('fittings') or [])} fitting plane(s), {len(lc)} line cut(s)")
                    if lc:
                        ax = AX.get(p.get('record')) or {}
                        x = ax.get('x') or [0, 0, 0]
                        perp = all(abs(sum(a * b for a, b in zip(c['normal'], x))) > 0.999 for c in lc)
                        vc = p.get('volume_change_pct')
                        if perp and vc is not None and -10 < vc < 0:
                            txt += ('; line cut perpendicular to the member: removed side = +normal (convention validated on 8.07-9.08); the other '
                                    f'side would delete {100 - abs(vc):.1f} % of the part, so the data fixes the side')
                        else:
                            col = 'AMBER'
                            txt += (f'; ESTIMATED SIDE: the line-cut plane is exact DB1 data (relation type 12), the removed side (+normal) follows '
                                    f'the convention validated on engines 8.07-9.08 only (engine {eng} not validated) - basis: that convention')
                    reasons.append(txt)
                elif e['kind'] == 'outline_despiked':
                    reasons.append(f"self-touching {e['role'].replace('_', ' ')} outline '{e['profile']}' split into its simple loop: zero-area "
                                   f"spike vertex/vertices {e['removed_vertices']} dropped ({e['db1_field']})")
        else:
            col = 'GREY'
            for e in p['events']:
                if e['kind'] == 'fitting_applied':
                    reasons.append(f"verified: the DB1 fitting plane lies on the member end (record length {e['L_record']} = fitted {e['L_fitted']} mm): "
                                   'the shipped geometry is already the fitted one')
                elif e['kind'] == 'polybeam_corners':
                    if e.get('all_corners_unchamfered'):
                        reasons.append(f"verified: DB1 chamfer type 0 (no chamfer) at every polybeam corner {e['chamfer_types']} -> Tekla mitres the "
                                       'segments; the straight segments with mitred corners are the stored geometry')
                    else:
                        col = 'AMBER'
                        reasons.append(f"polybeam corner chamfers in DB1 {e['chamfer_types']} not decoded: corners stay mitred (estimate)")
            if not p['events'] and p['name_source'] != p['name_completed']:
                reasons.append('verified: bolt group slot decision decoded from the DB1 slotted-parts mask (holes cut as Tekla does); label tag removed')
        if (col == 'GREEN' and kinds and set(kinds) == {'outline_despiked'} and p.get('volume_change_pct') == 0.0):
            col = 'GREY'
            reasons.append('the shipped solid was already right: completed STEP volume = shipped volume '
                           f"({p.get('volume_completed_mm3')} mm3); only the IFC outline is cleaned -> verified")
        colours[g] = {'colour': col, 'reasons': reasons}
    # plies of decided slotted groups that the mask leaves ROUND: unchanged + verified; the group's own product verified
    verified_round = {}
    SKP = {b['record']: [q['gid'] for q in b.get('plies') or [] if q.get('gid')] for b in sk.get('bolt_groups') or []}
    SKG = {b['record']: b.get('gid') for b in sk.get('bolt_groups') or []}
    for k, gr in (log.get('slot_groups') or {}).items():
        sl = set(gr.get('slotted_gid') or [])
        if not sl and gr.get('slotted'):
            rg = {q['record']: q['gid'] for b in sk.get('bolt_groups') or [] if str(b['record']) == k for q in b.get('plies') or []}
            sl = {rg.get(r) for r in gr['slotted']}
        bgid = gr.get('bolt_group_gid') or SKG.get(int(k))
        if bgid and bgid not in colours:
            colours[bgid] = {'colour': 'GREY', 'reasons': [f"verified: slot decision of bolt group {k} decoded from the DB1 slotted-parts mask "
                                                           f"({gr.get('how')}; mask {gr.get('mask')}): its plies are cut as Tekla cuts them"]}
        for gid in (gr.get('plies_head_first_gid') or SKP.get(int(k)) or []):
            if gid and gid not in sl and gid not in colours:
                verified_round.setdefault(gid, []).append(k)
    for gid, gs in verified_round.items():
        colours[gid] = {'colour': 'GREY', 'reasons': [f"verified: ply of slotted bolt group(s) {gs} that the DB1 'slotted holes in part 1..5' mask leaves ROUND "
                                                      '(round holes are Tekla\'s)']}
    # the baseline issue model's flags of this track -> resolved / still open
    track_cats = {'fitting_not_applied', 'slotted_holes_round', 'slotted_ply_round_holes', 'polybeam_straight_segments'}
    resolved, still, estimated = [], [], []
    for gid, ip in (iss.get('parts') or {}).items():
        cats = {f.get('category') for f in ip.get('flags') or []} & track_cats
        if not cats: continue
        c = colours.get(gid)
        row = {'gid': gid, 'baseline': sorted(cats), 'now': c['colour'] if c else None}
        (resolved if c and c['colour'] in ('GREEN', 'GREY') else estimated if c and c['colour'] == 'AMBER' else still).append(row)
    log['colour_by_part'] = colours
    log['baseline_track_flags'] = {'resolved_exact_or_verified': len(resolved), 'now_amber_estimate': len(estimated), 'still_open': still,
                                   'resolved_rows': resolved, 'amber_rows': estimated}
    cnt = {}
    for c in colours.values():
        cnt[c['colour']] = cnt.get(c['colour'], 0) + 1
    log['colour_counts'] = cnt
    if hss:
        e = [x for x in hss[0]['events'] if x['kind'] == 'fitting_applied']
        if e:
            log['independent_checks'] = [FIT_KISS.format(L=e[0]['L_fitted'], L0=e[0]['L_record'])]
    json.dump(log, open(outp, 'w'), indent=1)
    print(json.dumps({'colour_counts': cnt, 'baseline_resolved': len(resolved), 'baseline_amber': len(estimated), 'baseline_still_open': len(still)}))


if __name__ == '__main__':
    main()
