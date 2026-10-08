"""audit_bolts.py [KIT]: bolt / hole / washer audit of the decoder (default kit i_audit) on every old-engine data-3 model.
in : dec/<kit>/<id>.audit.json (per bolt: group, axis, flags, grip, hits, ply spans, head/washer/nut collision probes),
     dec/<kit>/<id>.json.parts.json.gz (decoded parts), rel/<id>.json (Tekla relation table), reports/<id>.json (model's own bolt list)
out: report/bolts_<kit>.json (per model + totals + examples)"""
import json, os, sys, gzip, collections, glob
import numpy as np
W = os.path.dirname(os.path.abspath(__file__)); os.chdir(W)
KIT = sys.argv[1] if len(sys.argv) > 1 else 'i_audit'
os.makedirs('report', exist_ok=True)
ENG = json.load(open('state/engines.json'))
T = collections.Counter(); EX = collections.defaultdict(list); per = {}
flagsT = collections.Counter(); relT = collections.Counter()


def ex(k, v, n=12):
    if len(EX[k]) < n: EX[k].append(v)


for ap in sorted(glob.glob(f'dec/{KIT}/*.audit.json')):
    i = os.path.basename(ap)[:-11]
    A = json.load(open(ap))
    pl = json.load(gzip.open(f'dec/{KIT}/{i}.json.parts.json.gz', 'rt')) if os.path.exists(f'dec/{KIT}/{i}.json.parts.json.gz') else []
    st = json.load(open(f'dec/{KIT}/{i}.json'))
    how = collections.Counter(r[4] for r in pl)
    status = {r[0]: (r[3], r[4]) for r in pl}
    B = A['bolts']; G = A['groups']; P = A['parts']
    r = {'engine': A.get('engine'), 'group_records': len(G), 'groups_written': how.get('bolt_group', 0), 'groups_holes_only': how.get('holes_only_group', 0),
         'groups_excluded': how.get('bolt_group_excluded', 0), 'bolts': len(B)}
    ho = [b for b in B if b['holes_only']]; real = [b for b in B if not b['holes_only']]
    r['bolts_holes_only'] = len(ho); r['bolts_real'] = len(real)
    r['bolts_axial_decoded'] = sum(1 for b in real if b['axial']); r['bolts_fitted'] = sum(1 for b in real if b.get('shift'))
    r['holes'] = sum(len(b['hits']) for b in B)
    r['holes_in_holes_only_groups'] = sum(len(b['hits']) for b in ho)
    hc = collections.Counter(min(len(b['hits']), 4) for b in B); r['holes_per_bolt'] = {str(k): v for k, v in sorted(hc.items())}
    r['real_bolts_without_hole'] = sum(1 for b in real if not b['hits']); r['holes_only_bolts_without_hole'] = sum(1 for b in ho if not b['hits'])
    for b in real:
        if not b['hits']: ex('real_bolt_without_hole', {'id': i[:12], 'gid': b['gid'], 'prof': G.get(str(b['gid']), {}).get('prof'), 'c': [round(x, 1) for x in b['c']]})
    # flags
    for b in real:
        k = f"wh{b.get('wash_head') or 0}-w2{b.get('wash_2') or 0}-wn{b.get('wash_nut') or 0}-n{b.get('nuts') or 0}"; flagsT[k] += 1
    r['flags'] = dict(collections.Counter(f"wh{b.get('wash_head') or 0}-w2{b.get('wash_2') or 0}-wn{b.get('wash_nut') or 0}-n{b.get('nuts') or 0}" for b in real))
    raw8 = collections.Counter()
    for g in G.values():
        p = (g.get('prof') or '').split('/')
        raw8[p[8] if len(p) > 8 else '<none>'] += 1
    r['flag_field_raw'] = dict(raw8.most_common(20))
    # grip vs plies (axial decoded bolts with ply spans)
    res_hi = []; res_lo = []
    for b in real:
        if not (b['axial'] and b['spans'] and b.get('grip')):
            continue
        off = b['zh'] - b['L'] / 2
        g0, g1 = b['grip'][0] - off, b['grip'][1] - off
        lo = min(s[0] for s in b['spans']); hi = max(s[1] for s in b['spans'])
        res_hi.append(hi - g1); res_lo.append(lo - g0)
        if abs(hi - g1) > 3 or abs(lo - g0) > 3:
            ex('grip_mismatch', {'id': i[:12], 'gid': b['gid'], 'prof': G.get(str(b['gid']), {}).get('prof'), 'ply': [round(lo, 2), round(hi, 2)], 'grip': [round(g0, 2), round(g1, 2)], 'hits': b['hits']})
    rh = np.abs(np.array(res_hi)) if res_hi else np.zeros(0); rl = np.abs(np.array(res_lo)) if res_lo else np.zeros(0)
    r['grip_checked'] = len(res_hi)
    r['grip_both_within_1mm'] = int(np.sum((rh <= 1) & (rl <= 1))); r['grip_both_within_3mm'] = int(np.sum((rh <= 3) & (rl <= 3)))
    r['grip_head_side_within_1mm'] = int(np.sum(rh <= 1)); r['grip_nut_side_within_1mm'] = int(np.sum(rl <= 1))
    r['grip_residual_p50_p95'] = [round(float(np.percentile(np.r_[rh, rl], q)), 2) for q in (50, 95)] if len(rh) else None
    # collision probes (head / washers / nuts vs written parts)
    pc = collections.Counter(); pc_ply = collections.Counter(); pc_other = collections.Counter()
    for b in real:
        for comp, (z0, z1, hits) in (b.get('probe') or {}).items():
            pc['probed_' + comp] += 1
            if hits:
                pc[comp] += 1
                if set(hits) & set(b['hits']): pc_ply[comp] += 1
                else: pc_other[comp] += 1
                ex('collision_' + comp, {'id': i[:12], 'gid': b['gid'], 'prof': G.get(str(b['gid']), {}).get('prof'), 'z': [z0, z1], 'parts': hits[:4],
                                         'part_profs': [P.get(str(h), {}).get('prof') for h in hits[:4]], 'plies': b['hits']}, 20)
    r['probe'] = {'probed': {k[7:]: v for k, v in pc.items() if k.startswith('probed_')}, 'colliding': {k: v for k, v in pc.items() if not k.startswith('probed_')},
                  'colliding_with_own_ply': dict(pc_ply), 'colliding_with_other_part': dict(pc_other)}
    # Tekla relation table: which relation type links bolt groups to parts, and do the holes go into those parts?
    rp = f'rel/{i}.json'
    if os.path.exists(rp):
        R = json.load(open(rp))
        gids = {int(k) for k in G}; pids = {int(k) for k in P}
        tl = {}
        for t, prs in R['pairs'].items():
            a_g = sum(1 for a, b, _ in prs if a in gids and b in pids); b_g = sum(1 for a, b, _ in prs if b in gids and a in pids)
            if a_g or b_g: tl[t] = {'group->part': a_g, 'part->group': b_g, 'records': len(prs)}
        r['relation_types_touching_groups'] = tl
        rel = collections.defaultdict(set)
        for t, prs in R['pairs'].items():
            if t not in tl: continue
            for a, b, _ in prs:
                if a in gids and b in pids: rel[a].add(b)
                if b in gids and a in pids: rel[b].add(a)
        H = collections.defaultdict(set)
        for b in B: H[b['gid']].update(b['hits'])
        holable = {int(k) for k, v in P.items() if v.get('region') and status.get(int(k), ('', ''))[0] == 'written'}
        tp = fp = fn = 0; fn_unholable = 0; norel_g = norel_h = 0; ho_g = {b['gid'] for b in B if b['holes_only']}; ho_norel = 0
        for g in gids:
            Rg = rel.get(g, set()); Hg = H.get(g, set())
            if not Rg and not Hg: continue
            if not Rg:
                norel_g += 1; norel_h += len(Hg); ho_norel += g in ho_g; continue
            tp += len(Hg & Rg); fp += len(Hg - Rg); fn += len((Rg & holable) - Hg); fn_unholable += len(Rg - holable - Hg)
            if Hg - Rg: ex('hole_in_unrelated_part', {'id': i[:12], 'gid': g, 'prof': G.get(str(g), {}).get('prof'), 'unrelated': sorted(Hg - Rg)[:5], 'related': sorted(Rg)[:8]})
            if (Rg & holable) - Hg: ex('related_part_not_holed', {'id': i[:12], 'gid': g, 'prof': G.get(str(g), {}).get('prof'), 'missing': sorted((Rg & holable) - Hg)[:5],
                                                                   'missing_profs': [P.get(str(x), {}).get('prof') for x in sorted((Rg & holable) - Hg)[:5]]})
        r['rel'] = {'group_part_pairs_holed_and_related': tp, 'holed_not_related': fp, 'related_not_holed': fn, 'related_not_holable': fn_unholable,
                    'groups_without_relation': norel_g, 'holes_of_groups_without_relation': norel_h, 'holes_only_groups_without_relation': ho_norel,
                    'groups_with_relation': sum(1 for g in gids if rel.get(g))}
        for k, v in r['rel'].items(): relT[k] += v
    # the model's own Tekla bolt report (bolt list: diameter, grade, length, quantity) vs decoded bolts
    import reports as RP
    reps = RP.model_reports(i)
    if reps:
        key = lambda b: (round(float(b.get('d_stored') or b['d']), 1), (b.get('standard') or '').upper().strip(), round(float(b['L']), 1))
        dec_real = collections.Counter(key(b) for b in real); dec_all = collections.Counter(key(b) for b in B)
        rr = []
        for x in reps:
            rep = collections.Counter()
            for (d_, g_, L_, site), q in x['rows'].items():
                rep[(d_, g_, L_)] += q
            keys = set(rep) | set(dec_real)
            diff = sum(abs(rep.get(k_, 0) - dec_real.get(k_, 0)) for k_ in keys)
            diff_all = sum(abs(rep.get(k_, 0) - dec_all.get(k_, 0)) for k_ in set(rep) | set(dec_all))
            rr.append({'file': x['file'], 'kind': x['kind'], 'date': x['date'], 'report_total': sum(rep.values()), 'decoded_real': len(real), 'decoded_incl_holes_only': len(B),
                       'rows': len(rep), 'rows_equal': sum(1 for k_ in rep if rep[k_] == dec_real.get(k_, 0)), 'abs_diff_real': diff, 'abs_diff_incl_holes_only': diff_all,
                       'exact': diff == 0, 'mismatch_rows': sorted([[list(k_), rep.get(k_, 0), dec_real.get(k_, 0)] for k_ in keys if rep.get(k_, 0) != dec_real.get(k_, 0)])[:12]})
        r['reports'] = rr
        bl_ = [x for x in rr if x['kind'] == 'bolt_list']
        if bl_:
            best = max(bl_, key=lambda x: x['date'] or '')
            T['report_models'] += 1; T['report_bolts'] += best['report_total']; T['report_decoded_real'] += best['decoded_real']
            T['report_decoded_incl_holes_only'] += best['decoded_incl_holes_only']
            T['report_exact_models'] += 1 if best['exact'] else 0; T['report_abs_diff'] += best['abs_diff_real']
            T['report_total_equal_models'] += 1 if best['report_total'] == best['decoded_real'] else 0
    for k in ('group_records', 'groups_written', 'groups_holes_only', 'groups_excluded', 'bolts', 'bolts_holes_only', 'bolts_real', 'bolts_axial_decoded',
              'bolts_fitted', 'holes', 'holes_in_holes_only_groups', 'real_bolts_without_hole', 'holes_only_bolts_without_hole', 'grip_checked',
              'grip_both_within_1mm', 'grip_both_within_3mm', 'grip_head_side_within_1mm', 'grip_nut_side_within_1mm'):
        T[k] += r.get(k) or 0
    for k, v in r['probe']['colliding'].items(): T['collide_' + k] += v
    for k, v in r['probe']['probed'].items(): T['probed_' + k] += v
    for k, v in r['probe']['colliding_with_own_ply'].items(): T['collide_ply_' + k] += v
    T['models'] += 1
    per[i] = r
json.dump({'kit': KIT, 'totals': dict(T), 'flags_total': dict(flagsT.most_common()), 'rel_total': dict(relT), 'per_model': per, 'examples': EX},
          open(f'report/bolts_{KIT}.json', 'w'), indent=1, default=str)
print(json.dumps({'totals': dict(T), 'flags': dict(flagsT.most_common(12)), 'rel': dict(relT)}, indent=1))
