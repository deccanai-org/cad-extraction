#!/usr/bin/env python3
"""print the essentials of one NC1 check result: explain.py <job id prefix> [label]"""
import json, sys, glob, os, collections
W = '/work/agentwork/sds2-recall-nc1'
pre = sys.argv[1]; lab = sys.argv[2] if len(sys.argv) > 2 else None
for f in sorted(glob.glob(os.path.join(W, 'out', 'nc1', pre + '*.json'))):
    if f.endswith('_selection.json'):
        continue
    d = json.load(open(f)); s = d['summary']
    if lab and s['label'] != lab:
        continue
    print('=' * 100); print(s['job'], s['label'], s.get('stage'), 'step MB', round((s.get('step_bytes') or 0) / 1e6), s['step_key'][-90:])
    print('sel', json.dumps(s.get('nc1_selection'))[:600])
    for k in ('nc1_parts', 'nc1_marks_distinct', 'nc1_holes', 'status', 'match_rate_parts', 'step_unique_pieces', 'step_pieces_with_holes_geometric',
              'step_holes_geometric', 'step_round_holes_geometric', 'step_slots_geometric', 'step_holes_by_kind', 'step_non_hole_arcs', 'manifest_holes',
              'manifest_counts', 'manifest_holes_not_cut', 'manifest_class'):
        print(' ', k, json.dumps(s.get(k), default=str)[:400])
    print('  matched', json.dumps(s['matched_parts']))
    for ro, v in s['by_role'].items():
        print('  role', ro, json.dumps(v))
    print('  approx matched', json.dumps(s['step_approx_matched']))
    rows = d['rows']
    c = collections.Counter((r['status'], r.get('step_kind'), r.get('step_approx')) for r in rows)
    print('  status x kind x approx', c.most_common(12))
    for st in ('missing_holes', 'extra_holes', 'count_equal'):
        rr = [r for r in rows if r['status'] == st]
        rr.sort(key=lambda r: -(r['nc1_holes'] - r.get('matched_holes', 0)))
        for r in rr[:4]:
            print(f"  {st:14s} {r['mark']:10s} {r['profile']:16s} L={r['length']:.0f} nc1={r['nc1_holes']} step={r.get('step_holes')} m={r.get('matched_holes')} dL={r.get('dL')} {r.get('length_match')} approx={r.get('step_approx')} nc1d={r.get('nc1_diameters')} stepd={r.get('step_diameters')} | {r.get('step_label','')[:70]}")
            print(f"      nc1x={r.get('nc1_hole_x', [])[:10]} stepx={r.get('step_hole_x', [])[:10]}")
    sz = [r for r in rows if r.get('strict_zero')]
    print('  strict_zero', len(sz), 'parts', sum(r['nc1_holes'] for r in sz), 'holes')
    for r in sorted(sz, key=lambda r: -r['nc1_holes'])[:8]:
        print(f"    SZ {r['mark']:10s} {r['profile']:16s} {r['code']} L={r['length']:.1f} W={r.get('width')} nc1={r['nc1_holes']} d={r.get('nc1_diameters')} cands={r['candidates']} approx={r.get('step_approx')} kind={r.get('step_kind')} | {r.get('step_label','')[:80]} | {r['file'][-60:]}")
