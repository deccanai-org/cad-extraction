#!/usr/bin/env python3
"""compare_ab.py ABDIR -> per job: v5.4 (a) vs patched (b2) skipped by reason, class, corpus, solids, wall"""
import json, os, sys, glob, re
ab = sys.argv[1]
rows = []
jobs = sorted({os.path.basename(p) for p in glob.glob(os.path.join(ab, '*', '*'))})
def load(v, j):
    d = os.path.join(ab, v, j)
    m = glob.glob(os.path.join(d, '*_manifest.json'))
    rc = open(os.path.join(d, 'rc.txt')).read().strip() if os.path.exists(os.path.join(d, 'rc.txt')) else None
    if not m: return dict(rc=rc)
    M = json.load(open(m[0])); c = M['counts']; s = M['skipped']
    return dict(rc=rc, cls=M.get('class'), corpus=M.get('corpus'), skipped=s.get('total'), by=s.get('by_reason'), solids=c.get('solids_written'),
                exact=c.get('pieces_exact'), approx=c.get('pieces_approx'), ref=c.get('reference_parts'), ref_open=c.get('reference_open_shells'),
                st=sum((M.get('standins') or {}).get('by_type', {}).values()), ratio=(M.get('weight_check') or {}).get('ratio'),
                rb=M.get('readback', {}), needed=s.get('needed'), table_empty=c.get('pieces_exact_without_table_data'),
                reasons=M.get('class_reasons'))
for j in jobs:
    a = load('a', j); b = load('b2', j)
    rows.append(dict(job=j, a=a, b=b))
    def f(x):
        if not x.get('cls') and x.get('cls') != 0: return f"rc={x.get('rc')}"
        rb = x['rb']
        return (f"class {x['cls']}{x['corpus']} skipped {x['skipped']} {x['by']} solids {x['solids']} exact {x['exact']} approx {x['approx']} "
                f"ref {x['ref']}/open {x['ref_open']} st {x['st']} ratio {x['ratio']} rb_inv {rb.get('invalid')} {x['rc']}")
    print(f"== {j}\n   A {f(a)}\n   B {f(b)}")
json.dump(rows, open(os.path.join(ab, 'compare.json'), 'w'), indent=1, default=str)
