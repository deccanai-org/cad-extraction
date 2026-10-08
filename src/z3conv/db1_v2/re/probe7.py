import sys, collections, numpy as np, re
from cache import *
from guidmap import db1_guids
import ifcbolts
db1, ifc = sys.argv[1:3]; N = int(sys.argv[3]) if len(sys.argv) > 3 else 4
db, pts, cs, lay, M = get(db1)
seqs = {m['seq']: m for m in M}
G, info = db1_guids(db.b)
B, GR = ifcbolts.bolts(ifc, True)
pairs = [(g, seqs[G[g['guid']]['key']]) for g in GR if g['guid'] in G and G[g['guid']]['key'] in seqs]
import random; random.seed(3); random.shuffle(pairs)
r33 = db.bystride[33]; b17 = db.I(r33 + 17)
for g, m in pairs[:N]:
    z = np.cross(m['x'], m['y'])
    print('\n', g['guid'][:8], 'd', round(g['d'], 2), 'L', round(g['L'], 2), 'nb', len(g['bolts']), 'memL', round(m['L'], 2), 'slot', g['pset'].get('Slotted hole x'), g['pset'].get('Slotted hole y'), 'hole', g['pset'].get('Bolt hole diameter'), 'W', g['pset'].get('Washer count'), 'N', g['pset'].get('Nut count'))
    for b in g['bolts']:
        r = b['start'] - m['O']; print('   bolt', np.round([r @ m['x'], r @ m['y'], r @ z], 2))
    k = int(db.I([m['off'] + 29])[0]); recs = db.lookup_all(k, 341)
    for o in recs:
        F = db.F(o + 17 + 4 * np.arange(80)); I = db.I(o + 9 + 4 * np.arange(82))
        print('   341 rec', o, 'idx13', int(db.I([o + 13])[0]))
        print('     F[17..]', [round(float(x), 3) if np.isfinite(x) and abs(x) < 1e7 else 'x' for x in F])
    for o in r33[b17 == m['seq']][:2]:
        ints = [int(x) for x in db.I(o + np.arange(9, 30, 4))]
        print('   33 rec', ints)
        for kk in ints[1:4]:
            for S, (K, O) in db.seqidx.items():
                lo, hi = np.searchsorted(K, kk, 'left'), np.searchsorted(K, kk, 'right')
                for oo in O[lo:hi][:2]:
                    raw = db.b[int(oo):int(oo) + S]
                    print('      ->', kk, 'stride', S, [(mm.start(), mm.group().decode('latin1')) for mm in re.finditer(rb'[\x20-\x7e]{2,}', raw)][:10])
