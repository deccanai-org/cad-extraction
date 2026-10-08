#!/usr/bin/env python3
"""Compare two step_check runs (kit step_check.py --parts) of the same model, before / after a fix.
usage: ab_compare.py BEFORE.json BEFORE.parts.jsonl.gz AFTER.json AFTER.parts.jsonl.gz
Reports totals (solids / valid / invalid / nonpos_vol / faces / bbox) and per part (matched by root order, pid+name
check): parts whose validity went valid->invalid (regressions), invalid->valid (fixed), volume change of parts that were
valid before (|dV|/V > 1e-6 flagged: the repair must not change the geometry of valid parts), bbox change."""
import sys, json, gzip


def load(p):
    return [json.loads(l) for l in gzip.open(p, 'rt') if l.strip()]


b, bp, a, ap = sys.argv[1:5]
B, A = json.load(open(b)), json.load(open(a))
PB, PA = load(bp), load(ap)
keys = ('roots', 'transferred', 'solids', 'checked', 'valid', 'invalid', 'nonpos_vol', 'faces', 'shells', 'empty_roots', 'bbox', 'render_ink')
print('total     ' + ' '.join(f'{k}={B.get(k)}->{A.get(k)}' for k in keys if B.get(k) != A.get(k) or k in ('valid', 'invalid')))
assert len(PB) == len(PA), (len(PB), len(PA))
fixed = regress = still = 0; dv_valid = []; dv_fixed = []; mism = 0; bbch = 0
for x, y in zip(PB, PA):
    if (x.get('pid'), x.get('name')) != (y.get('pid'), y.get('name')):
        mism += 1; continue
    xs, ys = x.get('solids') or 0, y.get('solids') or 0
    xv = xs > 0 and x.get('valid') == xs; yv = ys > 0 and y.get('valid') == ys
    if xv and not yv: regress += 1
    if not xv and yv and xs: fixed += 1
    if not xv and not yv and xs: still += 1
    if x.get('bbox') != y.get('bbox'):
        bbch += 1
    vx, vy = x.get('volume'), y.get('volume')
    if vx and vy and xv:
        r = abs(vy - vx) / abs(vx)
        if r > 1e-6:
            dv_valid.append((round(r, 6), x.get('name'), vx, vy, xs, ys))
    if vx is not None and vy is not None and not xv:
        dv_fixed.append((x.get('name'), vx, vy))
print(f'parts {len(PB)}: fixed(invalid->valid)={fixed} regress(valid->invalid)={regress} still_invalid={still} '
      f'name_mismatch={mism} bbox_changed={bbch} valid_parts_volume_changed={len(dv_valid)}')
for d in sorted(dv_valid, reverse=True)[:10]:
    print('   valid-part volume change', d)
for d in dv_fixed[:8]:
    print('   previously-invalid part volume before/after', d)
