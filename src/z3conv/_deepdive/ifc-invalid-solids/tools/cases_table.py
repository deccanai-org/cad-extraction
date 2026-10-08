#!/usr/bin/env python3
"""orig vs fix table over work/cases/{orig,fix}/<id> (run_case outputs): class, issues, solids/valid, nonpos, parts,
convert seconds, STEP bytes, per-part volume agreement with the source (join volume block) and per-part volume drift of
parts that were valid in orig (geometry of valid parts must not change).  usage: cases_table.py [--json OUT]"""
import os, sys, json, gzip, glob

W = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'cases')


def load_parts(p):
    try:
        return [json.loads(l) for l in gzip.open(p, 'rt') if l.strip()]
    except Exception:
        return []


rows = []
for d in sorted(glob.glob(os.path.join(W, 'orig', '*'))):
    m = os.path.basename(d)
    try:
        o = json.load(open(os.path.join(d, 'case.json'))); f = json.load(open(os.path.join(W, 'fix', m, 'case.json')))
    except Exception:
        continue
    def g(c):
        v = c.get('validate') or {}; st = c.get('step') or {}; j = c.get('join') or {}; vol = j.get('volume') or {}
        conv = [a for a in c.get('attempts') or [] if a.get('ok')]
        return {'class': c.get('class'), 'issues': c.get('issues'), 'solids': v.get('solids'), 'valid': v.get('valid'),
                'nonpos': v.get('nonpos_vol'), 'parts': st.get('parts'), 'bytes': st.get('bytes'),
                'conv_sec': conv[-1]['sec'] if conv else None, 'vol_checked': vol.get('checked'), 'vol_out5': vol.get('outside_5pct'),
                'surface_parts': j.get('surface_parts'), 'coverage': (j.get('coverage') or {}).get('all')}
    ro, rf = g(o), g(f)
    po = {p.get('pid'): p for p in load_parts(os.path.join(d, 'step_parts.jsonl.gz'))}
    pf = {p.get('pid'): p for p in load_parts(os.path.join(W, 'fix', m, 'step_parts.jsonl.gz'))}
    drift = []; reg = 0
    for pid, x in po.items():
        y = pf.get(pid)
        if not y:
            continue
        xs = x.get('solids') or 0; ys = y.get('solids') or 0
        xv = xs and x.get('valid') == xs; yv = ys and y.get('valid') == ys
        if xv and not yv:
            reg += 1
        if xv and x.get('volume') and y.get('volume') is not None:
            r = abs(y['volume'] - x['volume']) / abs(x['volume'])
            if r > 1e-4:
                drift.append((round(r, 4), x.get('name'), round(x['volume'], 1), round(y['volume'], 1)))
    try:
        sf = json.load(open(os.path.join(W, 'fix', m, 'out.step.stats.json'))).get('shellfix')
    except Exception:
        sf = None
    rows.append({'id': m, 'orig': ro, 'fix': rf, 'valid_parts_regressed': reg, 'valid_parts_volume_drift_gt_1e-4': len(drift),
                 'drift_examples': sorted(drift, reverse=True)[:5], 'shellfix': sf})
for r in rows:
    o, f = r['orig'], r['fix']
    print(f"{r['id']}  class {o['class']} -> {f['class']}  solids {o['solids']}/{o['valid']} valid -> {f['solids']}/{f['valid']}  "
          f"nonpos {o['nonpos']} -> {f['nonpos']}  conv {o['conv_sec']}s -> {f['conv_sec']}s  bytes {o['bytes']} -> {f['bytes']}  "
          f"vol5% {o['vol_out5']}/{o['vol_checked']} -> {f['vol_out5']}/{f['vol_checked']}  regress {r['valid_parts_regressed']}  "
          f"drift {r['valid_parts_volume_drift_gt_1e-4']}")
    print(f"      orig issues {o['issues']}  ->  fix issues {f['issues']}")
    if r['drift_examples']:
        print('      drift', r['drift_examples'])
if len(sys.argv) > 2 and sys.argv[1] == '--json':
    json.dump(rows, open(sys.argv[2], 'w'), indent=1)
