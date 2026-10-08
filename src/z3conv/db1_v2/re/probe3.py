import sys, collections, numpy as np, re
from cache import *
from guidmap import db1_guids
import ifcbolts
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
seqs = {m['seq']: m for m in M}
G, info = db1_guids(db.b)
B, GR = ifcbolts.bolts(ifc, True)
byg = {g['guid']: g for g in GR}
pairs = [(g, seqs[G[g['guid']]['key']]) for g in GR if g['guid'] in G and G[g['guid']]['key'] in seqs]
print('pairs', len(pairs))
def dd(o, n): return [round(float(x), 3) for x in db.D(o + np.arange(n) * 8)]
for g, m in pairs[:6]:
    z = np.cross(m['x'], m['y'])
    print('\n', g['guid'], 'd', round(g['d'], 2), 'L', round(g['L'], 2), 'nb', len(g['bolts']), 'memL', round(m['L'], 2), 'hole', g['pset'].get('Bolt hole diameter'), 'slot', g['pset'].get('Slotted hole x'), g['pset'].get('Slotted hole y'))
    O = m['O']
    for b in g['bolts']:
        r = b['start'] - O
        print('   bolt local (x,y,z)=', np.round([r @ m['x'], r @ m['y'], r @ z], 2), 'axis.z', round(float(b['axis'] @ z), 3), 'axis.y', round(float(b['axis'] @ m['y']), 3), 'axis.x', round(float(b['axis'] @ m['x']), 3))
    # poly chain
    key = int(db.I([m['off'] + lay['poly_field']])[0]); r1 = int(db.lookup([key], lay['poly_stride'])[0])
    print('   poly key', key, 'r1', r1, end=' ')
    if r1 >= 0:
        k2 = int(db.I([r1 + lay['poly_field2']])[0]); recs = db.lookup_all(k2, lay['poly_stride2'])
        print('k2', k2, 'outline recs', len(recs))
        for rr in recs[:2]:
            u = db.F(rr + lay['poly_ub'] + 4 * np.arange(10)); v = db.F(rr + lay['poly_vb'] + 4 * np.arange(10)); w = db.F(rr + lay['poly_ub'] + 80 + 4 * np.arange(10))
            print('     u', np.round(u, 2)); print('     v', np.round(v, 2)); print('     w', np.round(w, 2))
    else: print()
    # raw member record ints/doubles
    o = m['off']; print('   member rec ints', list(db.I(o + np.arange(9, 73, 4))))
    rr = db.attr_records(lay, m['attr'])
    if rr:
        a = rr[0]; S = int(db.lookup_stride([m['attr']])[0])
        # search doubles equal to d, L, hole
        hits = {}
        for k in range(9, S - 7):
            v = float(db.D([a + k])[0])
            for nm, t in (('d', g['d']), ('L', g['L']), ('hole', g['pset'].get('Bolt hole diameter') or -1), ('tol', (g['pset'].get('Bolt hole diameter') or 0) - g['d'])):
                if np.isfinite(v) and abs(v - t) < 0.02: hits.setdefault(nm, []).append(k)
            vf = float(db.F([a + k])[0])
            for nm, t in (('d', g['d']), ('L', g['L'])):
                if np.isfinite(vf) and abs(vf - t) < 0.02: hits.setdefault(nm + '_f', []).append(k)
        print('   attr', a, 'stride', S, 'hits', hits)
        print('   attr ints', list(db.I(a + np.arange(9, 60, 4))))
