#!/usr/bin/env python3
"""before/after evidence per case dir: grader counters (step_check) + per-root volume invariants.
  as_written = signed divergence volume of the original FACETED_BREP shells (lumps2.jsonl, faces exactly as written)
  occ_before / occ_after = sum of OCC solid volumes per root (occ_roots*.jsonl)
Roots whose OCC volume did not change and roots whose after-volume equals the as-written volume (0.5 %) are counted."""
import json, sys, collections
for d in sys.argv[1:]:
    A = json.load(open(d + '/chk_out.json')); B = json.load(open(d + '/chk_split2.json'))
    keys = ('solids', 'valid', 'invalid', 'nonpos_vol', 'render_ink')
    print(d, 'before', {k: A.get(k) for k in keys}, '\n' + ' ' * len(d), 'after ', {k: B.get(k) for k in keys})
    W = collections.defaultdict(float)
    for l in open(d + '/lumps2.jsonl'):
        x = json.loads(l); W[x['pd']] += sum(L['vol'] for L in x['lump_detail'])
    def load(p):
        o = {}
        for l in open(p):
            x = json.loads(l)
            o[x['i']] = (x['pd'], [s[0] for s in x.get('solids', [])], [s[2] for s in x.get('solids', [])])
        return o
    b0, b1 = load(d + '/occ_roots.jsonl'), load(d + '/occ_roots_split2.jsonl')
    c = collections.Counter()
    worst = []
    for i, (pd, v0, ok0) in b0.items():
        pd1, v1, ok1 = b1[i]
        s0 = sum(x for x in v0 if x is not None); s1 = sum(x for x in v1 if x is not None)
        w = W.get(pd, 0.0)
        npv0 = any(not (x and x > 0) for x in v0)
        c['roots'] += 1; c['roots_npv_before'] += npv0
        c['roots_npv_after'] += any(not (x and x > 0) for x in v1)
        same = abs(s1 - s0) <= 5e-3 * max(abs(s0), 1e-9)
        c['occ_vol_unchanged'] += same
        match_w = abs(s1 - w) <= 5e-3 * max(abs(w), 1e-9)
        c['after_eq_as_written'] += match_w
        if not npv0:
            c['clean_roots'] += 1; c['clean_roots_unchanged'] += same
        else:
            c['npv_roots_after_eq_as_written'] += match_w
        if not match_w:
            worst.append((round(s1 / w, 4) if w else None, i, round(s0, 1), round(s1, 1), round(w, 1)))
    print(' ' * len(d), dict(c))
    if worst:
        print(' ' * len(d), 'after != as_written (ratio, root, before, after, as_written):', sorted(worst, key=lambda t: abs((t[0] or 0) - 1), reverse=True)[:6])
