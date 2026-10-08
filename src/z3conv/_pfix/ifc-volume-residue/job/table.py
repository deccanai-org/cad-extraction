#!/usr/bin/env python3
"""per-model before / after table: live index (before) -> dev3 + kit census v2 -> dev3+openfix (dev3p) -> + census v3
(volume issue recomputed from census3_eval.jsonl; class re-derived the way finish_class does). Markdown on stdout."""
import os, json, collections
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
ms = json.load(open(D + '/../job/pkg/models.json'))
c3 = {}
for l in open(D + '/diag/census3_eval.jsonl'):
    d = json.loads(l)
    c3[d['wd'][:16]] = d
def cls_v3(case, n3):
    if case is None:
        return None
    if case.get('reasons'):
        return 3
    iss = [x for x in (case.get('issues') or []) if not x.startswith('parts_outside_volume_tolerance')]
    if n3:
        iss.append('vol')
    if iss or case.get('standins') or (case.get('coverage_all') is not None and case['coverage_all'] < 1):
        return 2
    return 1
rows = []; cnt = collections.Counter()
for o in ms:
    i = o['id'][:16]
    def lc(lbl):
        try:
            return json.load(open(f'{D}/{lbl}/{i}/case.json'))
        except Exception:
            return None
    a, b = lc('dev3'), (lc('dev3pc') or lc('dev3p'))       # patched: both patches (dev3pc) where run, else openfix only
    def vol(c):
        w = (c or {}).get('weight_ratio') or {}
        return f"{(w.get('outside_5pct') or 0) + (w.get('outside_curved_gross') or 0)}/{w.get('checked')}" if c and w else '-'
    v3 = c3.get(i)
    n3 = v3['v3'][0] if v3 and 'v3' in v3 else None
    others = sorted({x.split(':')[0] for x in ((b or a or {}).get('issues') or []) if not x.startswith('parts_outside')} |
                    {s['type'] for s in ((b or a or {}).get('standins') or [])})
    if (b or a) and (b or a).get('coverage_all') is not None and (b or a)['coverage_all'] < 1:
        others.append('coverage_%s' % (b or a)['coverage_all'])
    live_vol = next((x.split(':')[1] for x in o['issues_before'] if x.startswith('parts_outside')), '-')
    r = [i, o['group'], f"{o['size'] / 1e6:.1f}", str(o['class_before']), live_vol, str(a['class']) if a else 'oom', vol(a),
         str(b['class']) if b else ('oom' if not a else '-'), f"{n3}/{v3['v3'][1]}" if v3 and 'v3' in v3 else '-',
         str(cls_v3(b or a, n3)) if (b or a) else 'oom', ', '.join(others) or '']
    rows.append(r)
    cnt['before_1'] += o['class_before'] == 1; cnt['dev3_1'] += bool(a and a['class'] == 1); cnt['dev3p_1'] += bool(b and b['class'] == 1)
    cnt['v3_1'] += cls_v3(b or a, n3) == 1
    cnt['vol_before'] += 1; cnt['vol_dev3'] += bool(a and vol(a).split('/')[0] not in ('0', '-')); cnt['vol_v3'] += bool(n3)
print('| model | grp | MB | class live | vol outside live | class dev3 | vol outside dev3 (census v2) | class dev3+patches | vol outside census v3 | class dev3+patches + census v3 | other blockers |')
print('|---|---|---|---|---|---|---|---|---|---|---|')
for r in rows:
    print('| ' + ' | '.join(r) + ' |')
print()
print(json.dumps(dict(cnt)))
