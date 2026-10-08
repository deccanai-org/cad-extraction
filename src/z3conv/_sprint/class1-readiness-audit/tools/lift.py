"""lift.py PROJ_JSON : rank fix families by DB1 models lifted to class 1 (projected blockers per model; greedy cumulative order)."""
import json, sys, collections
FAM = {'bolt_nominal_head_nut': 'bolt_head_nut', 'hole_clearance_nominal': 'hole_tolerance', 'washer_nominal': 'washer_dims',
       'washer_side_inferred': 'washer2_side', 'bolt_axial_position_fitted': 'bolt_axial', 'bolt_axial_position_unknown': 'bolt_axial',
       'hole_slotted_cut_round': 'slotted_holes', 'approx_tagged_products': 'approx_name_tags', 'pieces_without_bolt_holes': 'bolt_groups_undecoded',
       'bolt_solid_no_hole': 'windows_pipeline_reuse'}


def fam(v):
    b = set()
    for t in v['standins']:
        b.add(FAM.get(t, 'sections' if t.startswith('section_') else ('step_stage' if t.startswith('v6_') else t)))
    for i in v['issues']:
        k = i.split(':')[0]
        b.add('cuts' if k == 'cuts_not_applied' else ('windows_pipeline_reuse' if k.startswith('inventory from the Windows') else
              ('step_stage' if k in ('parts_without_solid', 'invalid_solids', 'non_positive_volume_solids', 'parts_outside_volume_tolerance',
                                     'not_read_back_large_file', 'not_read_back_out_of_memory', 'step_vs_decoder_join_unavailable') else k)))
    prof = any('profile' in n for n in v['needs'])
    for n in v['needs']:
        b.add('profiles' if 'profile' in n else ('bolt_groups_undecoded' if 'bolt decoding' in n else n.split(':')[0]))
    if any(y is not None and y < 1 for y in v['coverage'].values()):
        b.add('profiles' if prof else ('bolt_groups_undecoded' if 'bolt_groups_undecoded' in b else 'coverage'))
    return b


if __name__ == '__main__':
    P = json.load(open(sys.argv[1]))
    M = {k: fam(v) for k, v in P.items() if v.get('projected') == 2}
    c1 = [k for k, v in P.items() if v.get('projected') == 1]
    print('projected class 1:', len(c1), [k[:12] for k in c1])
    print('class 2:', len(M))
    single = collections.Counter(next(iter(b)) for b in M.values() if len(b) == 1)
    print('blocked by exactly one family:', dict(single))
    occ = collections.Counter(f for b in M.values() for f in b)
    print('family occurrence (models):', dict(occ.most_common()))
    # greedy: pick the family that completes the most models given families already fixed
    fixed = set(); order = []
    left = dict(M)
    while True:
        best = None; gain = []
        for f in occ:
            if f in fixed: continue
            g = [k for k, b in left.items() if b <= fixed | {f}]
            if best is None or len(g) > len(gain): best, gain = f, g
        if not best or not gain: break
        fixed.add(best); order.append((best, len(gain), [k[:12] for k in gain]))
        for k in gain: left.pop(k)
    for f, n, ks in order: print(f'  +{f}: {n} more models -> class 1  {ks[:14]}')
    pairs = collections.Counter(tuple(sorted(b)) for b in left.values())
    print('remaining blocker sets (top):', pairs.most_common(8))
