#!/usr/bin/env python3
"""openings applied? per part with IfcRelVoidsElement openings (census 'op'): STEP volume of run B vs run A (A = v5,
which transcoded faceted bodies without their openings). usage: openings_cut.py SRC_PARTS A_STEP_PARTS B_STEP_PARTS"""
import sys, json, gzip, collections, statistics
src = [json.loads(l) for l in gzip.open(sys.argv[1], 'rt')]
A = {p['pid']: p for p in (json.loads(l) for l in gzip.open(sys.argv[2], 'rt')) if p.get('pid')}
B = {p['pid']: p for p in (json.loads(l) for l in gzip.open(sys.argv[3], 'rt')) if p.get('pid')}
r = []; c = collections.Counter()
for p in src:
    if not p.get('op'):
        continue
    a, b = A.get(p['gid']), B.get(p['gid'])
    if not a or not b or not a.get('volume') or not b.get('volume'):
        c['no_volume'] += 1
        continue
    x = b['volume'] / a['volume']
    r.append(x)
    c['cut (B < A by > 0.1%)' if x < 0.999 else ('same' if x < 1.001 else 'bigger')] += 1
print(json.dumps({'parts_with_openings': sum(1 for p in src if p.get('op')), 'compared': len(r), 'verdicts': dict(c),
                  'median_ratio': round(statistics.median(r), 4) if r else None, 'p10': round(sorted(r)[len(r) // 10], 4) if r else None}))
