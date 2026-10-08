#!/usr/bin/env python3
"""per-part comparison of two converter runs (sidecars <id>/out.step.parts.json):
part count, parts present, solids vs surfaces, per-part volume (solid parts in both), level/tag counts.
usage: cmp_sidecars.py DIR_A DIR_B [--tol 0.005]"""
import sys, os, json, glob, collections
A, B = sys.argv[1], sys.argv[2]
tol = float(sys.argv[sys.argv.index('--tol') + 1]) if '--tol' in sys.argv else 0.005
tot = collections.Counter()
rows = []
for pa in sorted(glob.glob(os.path.join(A, '*', 'out.step.parts.json'))):
    mid = pa.split('/')[-2]
    pb = os.path.join(B, mid, 'out.step.parts.json')
    if not os.path.exists(pb):
        continue
    a = {p['gid']: p for p in json.load(open(pa))['parts']}
    b = {p['gid']: p for p in json.load(open(pb))['parts']}
    c = collections.Counter()
    c['parts_a'] = len(a); c['parts_b'] = len(b)
    c['missing_in_b'] = len(set(a) - set(b)); c['extra_in_b'] = len(set(b) - set(a))
    for g in set(a) & set(b):
        x, y = a[g], b[g]
        sa, sb = x['solids'] > 0, y['solids'] > 0
        if sa and not sb: c['solid_to_surface'] += 1
        if sb and not sa: c['surface_to_solid'] += 1
        if sa and sb and x['volume_mm3'] > 0:
            r = y['volume_mm3'] / x['volume_mm3']
            if abs(r - 1) > tol:
                c['volume_changed'] += 1
                if len(c.get('ex', [])) if False else True:
                    pass
            else:
                c['volume_same'] += 1
    rows.append((mid, dict(c)))
    tot.update({k: v for k, v in c.items() if isinstance(v, int)})
for mid, c in rows:
    flag = ' <<' if c.get('missing_in_b') or c.get('solid_to_surface') or c.get('volume_changed') else ''
    print(mid, c, flag)
print('TOTAL', dict(tot))
