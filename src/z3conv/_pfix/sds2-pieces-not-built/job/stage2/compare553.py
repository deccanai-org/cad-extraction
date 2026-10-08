#!/usr/bin/env python3
"""compare553.py ABDIR LIVE_ROWS -> per job: live result, v5.5.3 (v553) vs v5.5.3 + patch (v553q)"""
import json, os, sys, glob
ab = sys.argv[1]
live = {}
for r in json.load(open(sys.argv[2])):
    live[r['step_key'].split('/')[-1].rsplit('_stage2', 1)[0]] = r
def load(v, j):
    d = os.path.join(ab, v, j)
    m = glob.glob(os.path.join(d, '*_manifest.json'))
    rc = open(os.path.join(d, 'rc.txt')).read().strip() if os.path.exists(os.path.join(d, 'rc.txt')) else None
    if not m: return dict(rc=rc)
    M = json.load(open(m[0])); c = M['counts']; s = M['skipped']; rb = M.get('readback') or {}
    return dict(rc=rc, cls=M.get('class'), corpus=M.get('corpus'), skipped=s.get('total'), by=s.get('by_reason'),
                solids=c.get('solids_written'), exact=c.get('pieces_exact'), approx=c.get('pieces_approx'),
                ref=c.get('reference_parts'), ref_open=c.get('reference_open_shells'), ref_fs=c.get('reference_face_sets'),
                st=sum((M.get('standins') or {}).get('by_type', {}).values()), ratio=(M.get('weight_check') or {}).get('ratio'),
                rb_top=rb.get('top_level_shapes'), rb_solids=rb.get('solids'), rb_valid=rb.get('valid'), rb_inv=rb.get('invalid'),
                rb_surf=rb.get('surfaces'), needed=s.get('needed'), source_absent=s.get('source_absent'),
                source_detail=(s.get('source_detail') or [])[:6], table_empty=c.get('pieces_exact_without_table_data'),
                reasons=M.get('class_reasons'))
rows = []
for j in sorted({os.path.basename(p) for p in glob.glob(os.path.join(ab, '*', '*'))}):
    a = load('v553', j); b = load('v553q', j); lv = live.get(j)
    rows.append(dict(job=j, live=None if lv is None else dict(conv=lv['conv'], cls=lv['cls'], issues=lv['issues'], only=lv['only']), v553=a, v553q=b))
json.dump(rows, open(os.path.join(ab, 'compare553.json'), 'w'), indent=1, default=str)
def f(x):
    if x.get('cls') is None: return f"rc={x.get('rc')}"
    return (f"c{x['cls']}{x['corpus']} skip {x['skipped']} {x['by']} | exact {x['exact']} approx {x['approx']} ref {x['ref']}/open {x['ref_open']}/fs {x['ref_fs']} "
            f"st {x['st']} w {x['ratio']} rb {x['rb_valid']}/{x['rb_solids']} inv {x['rb_inv']} surf {x['rb_surf']} te {x['table_empty']} [{x['rc']}]")
for r in rows:
    lv = r['live']
    print(f"== {r['job']}  live: {lv['conv'] + ' c' + str(lv['cls']) + ' ' + str(lv['issues'][:1]) if lv else '-'}")
    print(f"   v5.5.3  {f(r['v553'])}")
    print(f"   +patch  {f(r['v553q'])}")
