#!/usr/bin/env python3
"""estimate track (AMBER) of the pmp completion: for every gap of the 5 new samples that neither the source nor a standard
can fill, the most plausible geometry, with its basis and a confidence. Writes per sample
    complete/estimate/out/<tag>/patch.json          (pmp-completion-patch/1, see ../INTERFACES.md; read by the integration)
    complete/estimate/out/<tag>/estimate_log.json   (every estimate: what, where, basis, confidence, evidence; and every
                                                     gap we looked at but did not estimate, with the reason)
Pure python, deterministic (same inputs -> same ops; only generated_at differs). Geometry check: modal_estimate.py.

    python3 complete/estimate/make_estimates.py [--only n1_db1_small,...]
"""
import argparse
import json
import os

import est_common as E
import est_slots
import est_n2
import est_n4
import est_n5

ENGINE_ACC = {   # db1step.py code v comment: Tekla NC1 per-part slot selection vs rule v2 on 193 archives
    '7.82': {'agree': 5851, 'n': 5988, 'rate': 5851 / 5988}, '8.85': {'agree': 1706, 'n': 1806, 'rate': 1706 / 1806},
    '8.07': {'agree': 5943, 'n': 6067, 'rate': 5943 / 6067}, '8.44': {'agree': 1970, 'n': 2019, 'rate': 1970 / 2019},
    '8.62': {'agree': 286, 'n': 328, 'rate': 286 / 328}, '7.64': {'agree': 1246, 'n': 1249, 'rate': 1246 / 1249},
    '8.53': {'agree': 96, 'n': 96, 'rate': 1.0}}


def n1(tag):
    t = E.Tree(tag)
    skp = os.path.join(E.INPUTS, 'n1', 'skipped_records.json')
    t.add_input(skp)
    sk = json.load(open(skp))
    patch, log = E.new_patch(t), E.new_log(t)
    db1 = db1_slot_groups('n1')
    st, left_p, left_g = est_slots.estimate(t, sk, patch, log, 'v2_mask', engine_acc=ENGINE_ACC.get(str(sk['engine'])),
                                            db1_groups=db1)
    log['summary']['slotted_plies'] = st
    nc1 = est_slots.nc1_family_stats(os.path.join(E.INPUTS, 'n1', 'nc1'))
    log['cross_checks'] = {'package_nc1': dict(nc1, note='this package has 6 NC1 files; none is one of the slotted plies '
                                                      '(no slotted hole in any of them), so they neither confirm nor contradict')}
    if not db1:
        for q in sorted(left_p):
            log['not_estimated'].append({'part_id': q, 'category': 'slotted_ply_round_holes', 'why': 'no hole tool of the ply on the group axis'})
        for q in sorted(left_g):
            log['not_estimated'].append({'part_id': q, 'category': 'slotted_holes_round', 'why': 'group not decided'})
    if db1:
        log['db1_track_note'] = ('the db1 track decodes all 6 slotted groups from the DB1 (complete/db1/out/n1/restoration_log.json '
                                 'slot_groups, GREEN): our 10 slotted / 14 round ply estimates are withdrawn from the patch and kept '
                                 'here as a check of the rule - they agree with the decode on every ply')
    others = ('fitting_not_applied: Tekla fitting planes are decoded from the DB1 records (skipped_records.json '
              'fittings_not_applied) = source data, track db1 (GREEN); duplicate (YELLOW, 2): the DB1 holds both records, '
              'nothing to estimate')
    log['left_to_other_tracks'] = [others]
    return t, patch, log


def db1_slot_groups(short):
    """the db1 track's decoded slot groups for this sample (complete/db1/out/<n>/restoration_log.json), or {}.
    EST_NO_DB1_DEFER=1 ignores them (our AMBER slot ops are then emitted, e.g. if the db1 track ships no patch)"""
    if os.environ.get('EST_NO_DB1_DEFER') == '1':
        return {}
    for d in (short, {'n1': 'n1_db1_small', 'n2': 'n2_db1_addon'}[short]):
        p = os.path.join(E.COMPLETE, 'db1', 'out', d, 'restoration_log.json')
        if os.path.exists(p):
            return json.load(open(p)).get('slot_groups') or {}
    return {}


def db1_parts(short):
    if os.environ.get('EST_NO_DB1_DEFER') == '1':
        return {}
    for d in (short, {'n1': 'n1_db1_small', 'n2': 'n2_db1_addon'}[short]):
        p = os.path.join(E.COMPLETE, 'db1', 'out', d, 'restoration_log.json')
        if os.path.exists(p):
            return json.load(open(p)).get('parts') or {}
    return {}


def run(tags):
    fns = {'n1_db1_small': n1, 'n2_db1_addon': est_n2.make, 'n4_ifc_c2s': est_n4.make, 'n5_sds2': est_n5.make}
    import n3_check
    fns['n3_ifc_approx'] = n3_check.make
    for tag in tags:
        if tag not in fns:
            continue
        t, patch, log = fns[tag](tag) if tag != 'n2_db1_addon' else est_n2.make(tag, ENGINE_ACC, db1_slot_groups('n2'), db1_parts('n2'))
        if patch is None:
            continue
        cnt = {}
        for o in patch['ops']:
            cnt[o['op']] = cnt.get(o['op'], 0) + 1
        log['summary']['ops'] = cnt
        log['summary']['parts_touched'] = len({o.get('part_id') or o['id'] for o in patch['ops']})
        log['summary']['estimates'] = len(log['estimates'])
        log['summary']['not_estimated'] = len(log['not_estimated'])
        import hashlib
        ops_sha = hashlib.sha256(json.dumps(patch['ops'], sort_keys=True).encode()).hexdigest()
        log['summary']['ops_sha256'] = ops_sha
        gc = os.path.join(E.OUT, tag, 'geometry_check.json')
        if os.path.exists(gc):
            rep = json.load(open(gc))
            if rep.get('ops_sha256') == ops_sha:
                vals = list(rep['parts'].values())
                log['geometry_check'] = {
                    'how': 'Modal app pmp-estimate (complete/estimate/modal_estimate.py): the estimate patch merged alone into the '
                           'baseline schedules with the integration\'s completion_core.merge, every changed part built with the '
                           'baseline\'s shipped steelbuild.py, each solid checked (BRepCheck valid, closed, volume > 0), target '
                           'volume within tolerance',
                    'ops_sha256': ops_sha, 'parts_checked': rep['n_parts_checked'], 'parts_ok': rep['n_ok'],
                    'solids': sum(v.get('solids', 0) for v in vals), 'problems': rep['problems'],
                    'file': f'complete/estimate/out/{tag}/geometry_check.json'}
            else:
                log['geometry_check'] = {'stale': True, 'note': 'patch changed since the last Modal check: re-run modal_estimate.py'}
        d = E.write_out(tag, patch, log)
        print(tag, '->', d, cnt, 'estimates', len(log['estimates']), 'not_estimated', len(log['not_estimated']))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='')
    a = ap.parse_args()
    tags = [x for x in a.only.split(',') if x] or list(E.SHORT)
    run(tags)
