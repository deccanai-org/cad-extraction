import sys, collections, numpy as np, re
from cache import *
from guidmap import db1_guids
import ifcbolts
db1, ifc = sys.argv[1:3]; N = int(sys.argv[3]) if len(sys.argv) > 3 else 3
db, pts, cs, lay, M = get(db1)
seqs = {m['seq']: m for m in M}
G, info = db1_guids(db.b)
B, GR = ifcbolts.bolts(ifc, True)
pairs = [(g, seqs[G[g['guid']]['key']]) for g in GR if g['guid'] in G and G[g['guid']]['key'] in seqs]
import random; random.seed(1); random.shuffle(pairs)
def show(o, S, tag):
    raw = db.b[o:o + S]
    strs = [(mm.start(), mm.group().decode('latin1')) for mm in re.finditer(rb'[\x20-\x7e]{2,}', raw)]
    dbl = [(k, round(float(db.D([o + k])[0]), 3)) for k in range(9, S - 7) if np.isfinite(db.D([o + k])[0]) and 0.5 < abs(db.D([o + k])[0]) < 1e6 and abs(db.D([o+k])[0] * 1000 - round(db.D([o+k])[0] * 1000)) < 1e-6]
    print(f'   [{tag}] off {o} stride {S} strs {strs[:20]}')
    print(f'        doubles {dbl[:30]}')
    print(f'        ints {[(k, int(db.I([o+k])[0])) for k in range(9, min(S, 120), 4)]}')
for g, m in pairs[:N]:
    z = np.cross(m['x'], m['y'])
    print('\n', g['guid'], 'd', round(g['d'], 2), 'L', round(g['L'], 2), 'nb', len(g['bolts']), 'memL', round(m['L'], 2), 'pset', {k: v for k, v in g['pset'].items() if k not in ('id',)})
    for b in g['bolts']:
        r = b['start'] - m['O']
        print('   bolt local', np.round([r @ m['x'], r @ m['y'], r @ z], 2), 'axis', np.round([b['axis'] @ m['x'], b['axis'] @ m['y'], b['axis'] @ z], 3))
    o = m['off']
    for f in range(13, 41, 4):
        k = int(db.I([o + f])[0])
        for S, (K, O) in db.seqidx.items():
            lo, hi = np.searchsorted(K, k, 'left'), np.searchsorted(K, k, 'right')
            for oo in O[lo:hi][:3]: show(int(oo), S, f'member+{f} -> key {k}')
    # records keyed by seq
    for S, (K, O) in db.seqidx.items():
        lo, hi = np.searchsorted(K, m['seq'], 'left'), np.searchsorted(K, m['seq'], 'right')
        for oo in O[lo:hi][:4]:
            if S != 73: show(int(oo), S, 'keyed by seq')
