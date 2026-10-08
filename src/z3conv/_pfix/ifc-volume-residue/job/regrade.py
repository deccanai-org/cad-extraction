#!/usr/bin/env python3
"""before / census-only / after joins for the test models (small jsonl files; runs in seconds)"""
import sys, os, json, gzip, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'kit'))
import grade_join as G
D = os.path.dirname(os.path.abspath(__file__)) + '/../data'
ms = json.load(open(D + '/../job/pkg/models.json'))
def n_out(j):
    v = j.get('volume') or {}
    return (v.get('outside_5pct') or 0) + (v.get('outside_curved_gross') or 0), v.get('checked')
rows = []
for o in ms:
    i = o['id'][:16]
    try:
        os_, ot = G.load(f'{D}/old/{i}.src_parts.jsonl.gz'), G.load(f'{D}/old/{i}.step_parts.jsonl.gz')
    except Exception as e:
        os_ = ot = None
    try:
        ns, nt = G.load(f'{D}/dev3/{i}/src_parts.jsonl.gz'), G.load(f'{D}/dev3/{i}/step_parts.jsonl.gz')
    except Exception:
        ns = nt = None
    cv_old = collections.Counter(p.get('cv') or 1 for p in os_) if os_ else None
    a = G.join(os_, ot) if os_ else {}
    b = G.join(ns, ot) if (ns and ot) else {}
    c = G.join(ns, nt) if (ns and nt) else {}
    r = {'id': i, 'group': o['group'], 'cv_old': dict(cv_old) if cv_old else None, 'live_issue': [x for x in o['issues_before'] if 'volume' in x],
         'before': n_out(a) if a else None, 'mode_before': a.get('mode'), 'census_v2_old_step': n_out(b) if b else None, 'mode_b': b.get('mode'),
         'after_dev3': n_out(c) if c else None}
    rows.append(r)
    print(json.dumps(r))
