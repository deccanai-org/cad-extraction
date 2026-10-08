#!/usr/bin/env python3
"""summarise class1check.jsonl.gz: double body representations and faceted B-rep voids in class-1 IFC models"""
import json, gzip, collections, os
D = os.path.dirname(os.path.abspath(__file__))
C = collections.Counter
rows = [json.loads(l) for l in gzip.open(os.path.join(D, 'box_out/class1check.jsonl.gz'), 'rt')]
out = {'models': len(rows), 'errors': sum(1 for r in rows if r.get('error') or not r.get('g2'))}
mb = C(); bv = C(); vmb = C(); vbv = C(); mb_ex = []; bv_ex = []
for r in rows:
    g = r.get('g2') or {}; i = r.get('info') or {}
    code = i.get('code') or ('reused-v5' if i.get('reused') else 'none')
    if g.get('multi_body'):
        mb[code] += 1
        for s in g.get('multi_body_samples') or []:
            vmb[(code, s.get('verdict'))] += 1
            if s.get('verdict') == 'step_double' and len(mb_ex) < 8:
                mb_ex.append([r['id'][:16], code, s.get('cls'), s.get('name'), s.get('reps'), s.get('step_over_body'), s.get('step_over_sum_reps')])
    if g.get('brep_voids'):
        bv[code] += 1
        for s in g.get('brep_voids_samples') or []:
            vbv[(code, s.get('verdict'))] += 1
            if s.get('verdict') == 'step_voids_as_solids' and len(bv_ex) < 8:
                bv_ex.append([r['id'][:16], code, s.get('cls'), s.get('name'), s.get('outer_shell_mm3'), s.get('voids_mm3'), s.get('step_vol')])
out['multi_body_models_by_code'] = dict(mb); out['multi_body_sample_verdicts'] = {f'{a}|{b}': n for (a, b), n in vmb.items()}
out['multi_body_ids'] = C(x for r in rows for x, n in ((r.get('g2') or {}).get('multi_body_ids') or [])).most_common(6)
out['multi_body_examples'] = mb_ex
out['brep_voids_models_by_code'] = dict(bv); out['brep_voids_sample_verdicts'] = {f'{a}|{b}': n for (a, b), n in vbv.items()}
out['brep_voids_examples'] = bv_ex
out['models_double_confirmed'] = sorted({r['id'] for r in rows for s in ((r.get('g2') or {}).get('multi_body_samples') or []) if s.get('verdict') == 'step_double'})
out['models_voids_as_solids_confirmed'] = sorted({r['id'] for r in rows for s in ((r.get('g2') or {}).get('brep_voids_samples') or []) if s.get('verdict') == 'step_voids_as_solids'})
json.dump(out, open(os.path.join(D, 'class1check_summary.json'), 'w'), indent=1)
print(json.dumps({k: v for k, v in out.items() if not k.startswith('models_')}, indent=1))
print('double confirmed models', len(out['models_double_confirmed']), 'voids-as-solids confirmed models', len(out['models_voids_as_solids_confirmed']))
