"""analyze2.py : before/after of the final hole-tolerance patch over every old-engine data-3 DB1 (harness on the kit's own convert path, code j base)
baseline = kit_jg (deployed code j + catalog crash guard only), patched = kit_jp5 (code j + hole_tolerance_residue.patch); kit_i = deployed code i as is"""
import json, glob, gzip, collections
idx = {r['id']: r for r in (json.loads(l) for l in gzip.open('../s3now/index.jsonl.gz')) if r.get('pipeline') == 'db1'}
MOD = {m['id']: m for m in json.load(open('../remote/models2.json'))}
old = [h for h, m in MOD.items() if m['engine'] in ('6.87', '7.01', '7.24')]
def load(k):
    R = {}
    for f in glob.glob(f'census/{k}/*.json'):
        r = json.load(open(f)); R[r['sha256']] = r
    return R, sorted(f.split('/')[-1][:12] for f in glob.glob(f'census/{k}/*.err'))
I, Ie = load('kit_i'); G, Ge = load('kit_jg'); P, Pe = load('kit_jp5')
hn_idx = lambda h: next((s['count'] for s in (idx[h].get('standins') or []) if s['type'] == 'hole_clearance_nominal'), 0)
bs = lambda r: (r or {}).get('bolt_stats') or {}
nom = lambda r: bs(r).get('holes_nominal_clearance', 0) if r else None
out = {'models_old_engine': len(old), 'have': {'kit_i': len(I), 'kit_jg': len(G), 'kit_jp5': len(P)}, 'errors': {'kit_i': Ie, 'kit_jg': Ge, 'kit_jp5': Pe}}
cause = collections.Counter(); cmods = collections.Counter(); rows = []; inside_prof = collections.Counter(); acct_bad = []; other_diff = []
for h in old:
    g, p, i = G.get(h), P.get(h), I.get(h)
    c = {k: v for k, v in ((g or {}).get('holes_by_cause_deployed_rule') or {}).items() if k != 'decoded'}
    for k, v in c.items(): cause[k] += v; cmods[k] += 1
    a, b = bs(g), bs(p)
    for k, v in (b.get('bolt_inside_part_profiles') or {}).items(): inside_prof[k] += v
    if g and p:
        if a.get('holes_cut', 0) != b.get('holes_cut', 0) + b.get('holes_not_cut_zero_diameter', 0) + b.get('holes_not_cut_bolt_inside_part', 0):
            acct_bad.append((h[:12], a.get('holes_cut'), b.get('holes_cut'), b.get('holes_not_cut_zero_diameter'), b.get('holes_not_cut_bolt_inside_part')))
        keys = ('groups', 'bolts', 'bolts_with_holed_part', 'bolts_axial_decoded', 'bolts_shifted_to_plies', 'washers', 'washers_nominal',
                'nominal_head_nut_bolts', 'holes_only_bolts', 'standard_table_geometry', 'model_catalog_bolts')
        d = {k: (a.get(k), b.get(k)) for k in keys if a.get(k) != b.get(k)}
        if (g.get('status'), g.get('members')) != (p.get('status'), p.get('members')): d['status'] = (g.get('status'), p.get('status'))
        if d: other_diff.append((h[:12], d))
    rows.append({'id': h[:12], 'engine': MOD[h]['engine'], 'index_class': idx[h].get('class'), 'index_code': idx[h].get('converter_code'),
                 'index_hn': hn_idx(h), 'code_i': ('crash' if h[:12] in Ie else (i or {}).get('status')), 'code_i_hn': nom(i),
                 'baseline_hn': nom(g), 'patched_hn': nom(p), 'baseline_holes': a.get('holes_cut'), 'patched_holes': b.get('holes_cut'),
                 'no_hole': b.get('holes_not_cut_zero_diameter'), 'inside': b.get('holes_not_cut_bolt_inside_part'),
                 'slot_round': b.get('holes_in_slotted_groups_cut_round'), 'patched_src': b.get('holes_by_diameter_source'), 'causes': c})
out['baseline_nominal_by_cause'] = dict(cause); out['baseline_models_by_cause'] = dict(cmods)
tot = lambda k, rs: sum((r[k] or 0) for r in rs)
for name, rs in (('index_tagged', [r for r in rows if r['index_hn'] > 0]), ('all_old_engine', rows)):
    out[name] = {'models': len(rs), 'index_hn': tot('index_hn', rs), 'code_i_hn': tot('code_i_hn', rs), 'baseline_hn': tot('baseline_hn', rs),
                 'patched_hn': tot('patched_hn', rs), 'models_index_hn_gt0': sum(1 for r in rs if r['index_hn'] > 0),
                 'models_baseline_hn_gt0': sum(1 for r in rs if (r['baseline_hn'] or 0) > 0), 'models_patched_hn_gt0': sum(1 for r in rs if (r['patched_hn'] or 0) > 0),
                 'models_code_i_crash': sum(1 for r in rs if r['code_i'] == 'crash'), 'baseline_holes': tot('baseline_holes', rs),
                 'patched_holes': tot('patched_holes', rs), 'no_hole': tot('no_hole', rs), 'inside': tot('inside', rs), 'slot_round': tot('slot_round', rs),
                 'models_missing_pair': [r['id'] for r in rs if r['baseline_hn'] is None or r['patched_hn'] is None]}
src = collections.Counter()
for r in rows:
    for k, v in (r['patched_src'] or {}).items(): src[k] += v
out['patched_holes_by_source'] = dict(src); out['bolt_inside_part_profiles'] = dict(inside_prof.most_common(25))
out['hole_accounting_mismatches'] = acct_bad; out['other_bolt_stats_differences'] = other_diff
latent = [r for r in rows if r['index_hn'] == 0 and (r['baseline_hn'] or 0) > 0]
out['latent_models_tag_on_rerun_without_patch'] = {'models': len(latent), 'holes': tot('baseline_hn', latent), 'ids': [r['id'] for r in latent]}
out['rows'] = sorted(rows, key=lambda r: -(r['index_hn'] or 0))
json.dump(out, open('analysis_final.json', 'w'), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, indent=1)[:7000])
