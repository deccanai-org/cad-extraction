#!/usr/bin/env python3
"""check the Tekla quantity-basis hypothesis on the attribution records: NetVolume computed on the profile WITHOUT root
fillets / corner radii -> E_corr = q * A(radii) / A(sharp) from the profile's own parameters"""
import json, re, math, glob, collections, sys
def parse(items):
    m = re.search(r'Extr\[(\w+)ProfileDef\(([^)]*)\)', items[0]) if items else None
    if not m:
        return None, None
    return m.group(1), {k: float(v) for k, v in (kv.split('=') for kv in m.group(2).split(',') if '=' in kv)}
def areas(t, g):
    """(area with radii, area sharp) in the profile's units, None if not handled"""
    if t == 'RectangleHollow':
        x, y, w = g['XDim'], g['YDim'], g['WallThickness']
        ro, ri = g.get('OuterFilletRadius', 0), g.get('InnerFilletRadius', 0)
        s = x * y - (x - 2 * w) * (y - 2 * w)
        return s - (4 - math.pi) * (ro * ro - ri * ri), s
    if t == 'IShape':
        b, h, tw, tf = g['OverallWidth'], g['OverallDepth'], g['WebThickness'], g['FlangeThickness']
        r = g.get('FilletRadius', 0)
        s = 2 * b * tf + (h - 2 * tf) * tw
        return s + (4 - math.pi) * r * r, s
    if t == 'LShape':
        h, b, th = g['Depth'], g.get('Width', g['Depth']), g['Thickness']
        r = g.get('FilletRadius', 0)
        s = th * (h + b - th)
        return s + (1 - math.pi / 4) * r * r, s
    if t == 'UShape':
        h, b, tw, tf = g['Depth'], g['FlangeWidth'], g['WebThickness'], g['FlangeThickness']
        r = g.get('FilletRadius', 0)
        s = 2 * b * tf + (h - 2 * tf) * tw
        return s + 2 * (1 - math.pi / 4) * r * r, s
    if t == 'TShape':
        h, b, tw, tf = g['Depth'], g['FlangeWidth'], g['WebThickness'], g['FlangeThickness']
        r = g.get('FilletRadius', 0)
        s = b * tf + (h - tf) * tw
        return s + (2 - math.pi / 2) * r * r, s
    return None
stat = collections.Counter(); ex = collections.defaultdict(list)
for fn in sorted(glob.glob('*/attrib.json')):
    d = json.load(open(fn))
    if not any('Tekla' in a for a in d.get('apps') or []):
        continue
    for p in d['parts']:
        if p['census'].get('qk') not in ('net', 'gross') or not p['S']:
            continue
        t, g = parse(p['items'])
        ar = areas(t, g) if t else None
        r0 = p['S'] / p['E']
        if not ar or ar[1] <= 0:
            stat[(p['kind'], 'no_profile', abs(r0 - 1) <= 0.05)] += 1
            if p['kind'] == 'outside': ex['no_profile'].append((fn[:16], p['name'], p['items'][0][:90] if p['items'] else None, round(r0, 4)))
            continue
        Ec = p['E'] * ar[0] / ar[1]
        r1 = p['S'] / Ec
        stat[(p['kind'], t, abs(r0 - 1) <= 0.05, abs(r1 - 1) <= 0.05)] += 1
        if abs(r1 - 1) > 0.05 and p['kind'] == 'outside':
            ex[t].append((fn[:16], p['name'], round(r0, 4), round(r1, 4), p['items'][0][:150]))
for k, v in sorted(stat.items(), key=lambda kv: str(kv[0])):
    print(k, v)
for t, l in ex.items():
    print('== still outside after correction:', t, len(l))
    for x in l[:12]: print('   ', x)
