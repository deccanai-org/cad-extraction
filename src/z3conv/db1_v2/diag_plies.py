"""for bolts whose ply grip centre disagrees with the record zc: show zc, cut length, plies, truth head z"""
import sys, json, collections, numpy as np
sys.path.insert(0, 're'); sys.path.insert(0, '.')
from cache import get
from guid2 import guid_keys
import db1bolts2, db1bolts, db1step, ifcbolts
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
bd = db1bolts2.BoltDecoder(db, pts, cs, lay); G = bd.decode(M); bys = {g['seq']: g for g in G}
cat = json.load(open('tekla_profiles.json'))
out = db1step.IfcOut('x')
parts = {}; REG = {}
for m in M:
    if m.get('cut') or m['seq'] in bys: continue
    kind, v, how = db1step.section_for(m['prof'], cat)
    if kind is None and v == 'contour_plate':
        poly = db.polygon(lay, m)
        try: thick = float(db1step.re.findall(r'[\d.]+', m['prof'])[0])
        except Exception: continue
        if poly: parts[m['seq']] = (out.plate_frame(m, thick), thick); REG[m['seq']] = ([tuple(q) for q in poly], [])
        continue
    if kind is None: continue
    r = db1bolts.outline(kind, v)
    if r is None: continue
    parts[m['seq']] = (out.member_frame(m), m['L']); REG[m['seq']] = r
links = bd.links(set(bys), set(parts))
GK, _, _ = guid_keys(db); _, GR = ifcbolts.bolts(ifc, True)
n = 0; stats = collections.Counter()
for tb in GR:
    g = bys.get(GK.get(tb['guid']))
    if g is None or not tb['bolts'] or (g.get('flagbits') or {}).get('bolt') is False: continue
    a = db.lookup_all(g['attr'])[0]; S = int(db.lookup_stride([g['attr']])[0]); C = float(db.F([a + S - 28])[0])
    for (u, v), P0 in zip(g['uv'], g['world']):
        T = [b for b in tb['bolts'] if np.linalg.norm([(b['start'] - g['O']) @ g['x'] - u, (b['start'] - g['O']) @ g['y'] - v]) < 1]
        if not T: continue
        zh_t = (T[0]['start'] - g['O']) @ g['z']
        iv = []
        for s in links.get(g['seq'], []):
            if s in parts:
                for t0, t1 in db1bolts2.line_intervals(parts[s][0], parts[s][1], REG[s], P0, g['z']): iv.append((round(t0, 2), round(t1, 2), s))
        if not iv: continue
        glo = min(x[0] for x in iv); ghi = max(x[1] for x in iv)
        if abs((glo + ghi) / 2 - g['zc']) < 1: continue
        # clipped to the cut length window around z = 0
        for nm, (wlo, whi) in (('sym', (-abs(C) / 2, abs(C) / 2)), ('zc', (g['zc'] - abs(C) / 2, g['zc'] + abs(C) / 2))):
            cl = [(max(a_, wlo), min(b_, whi)) for a_, b_, s in iv if b_ > wlo and a_ < whi]
            if cl:
                lo, hi = min(x[0] for x in cl), max(x[1] for x in cl)
                stats[(nm, 'centre_ok', abs((lo + hi) / 2 - g['zc']) < 1)] += 1
                stats[(nm, 'head_ok', abs(hi + (db1bolts.washer_t({'d': g['d'], 'std': None}) * 0) - zh_t) < 1)] += 1
        n += 1
        if n <= 8: print('zc', round(g['zc'], 2), 'C', round(C, 1), 'truth zh', round(float(zh_t), 2), 'L', g['L'], 'plies', iv[:4], 'W1', (g.get('flagbits') or {}).get('w1'))
print(stats)
