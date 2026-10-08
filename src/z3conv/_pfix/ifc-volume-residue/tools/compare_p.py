#!/usr/bin/env python3
"""dev3 vs dev3p per model: class, coverage, parts, parts without geometry, opening repair stats, and per-part STEP
volume differences (gid join) - runs on the downloaded small files in seconds"""
import os, json, gzip, glob, collections
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
def load(p):
    out = {}
    try:
        for l in gzip.open(p, 'rt'):
            r = json.loads(l)
            if r.get('pid'):
                out.setdefault(r['pid'], r)
    except Exception:
        pass
    return out
rows = []
LBL = os.environ.get('LABEL', 'dev3p')
for d in sorted(glob.glob(D + '/' + LBL + '/*/case.json')):
    i = d.split('/')[-2]
    try:
        a = json.load(open(f'{D}/dev3/{i}/case.json')); b = json.load(open(d))
        sa = json.load(open(f'{D}/dev3/{i}/out.step.stats.json')); sb = json.load(open(f'{D}/{LBL}/{i}/out.step.stats.json'))
    except Exception as e:
        print(i, 'missing', e); continue
    pa, pb = load(f'{D}/dev3/{i}/step_parts.jsonl.gz'), load(f'{D}/{LBL}/{i}/step_parts.jsonl.gz')
    changed = []
    for g, x in pb.items():
        y = pa.get(g)
        if y is None:
            changed.append((g, None, x.get('volume'))); continue
        va, vb = y.get('volume'), x.get('volume')
        if (va or 0) != (vb or 0) and not (va and vb and abs(va - vb) <= 1e-6 * max(abs(va), abs(vb))):
            changed.append((g, va, vb))
    lost = [g for g in pa if g not in pb]
    r = {'id': i, 'class': [a['class'], b['class']], 'cov': [a.get('coverage_all'), b.get('coverage_all')], 'parts': [sa.get('parts'), sb.get('parts')],
         'nogeom': [sa.get('parts_without_geometry'), sb.get('parts_without_geometry')], 'repair': sb.get('opening_shell_repair'),
         'vol_changed': len(changed), 'new_parts': sum(1 for c in changed if c[1] is None), 'lost_parts': len(lost),
         'issues': [a.get('issues'), b.get('issues')], 'out_bytes': [sa.get('out_bytes'), sb.get('out_bytes')]}
    rows.append(r)
    print(json.dumps(r))
print('models', len(rows), 'class changes', [(r['id'], r['class']) for r in rows if r['class'][0] != r['class'][1]],
      'vol changes', sum(r['vol_changed'] for r in rows), 'new parts', sum(r['new_parts'] for r in rows), 'lost', sum(r['lost_parts'] for r in rows))
