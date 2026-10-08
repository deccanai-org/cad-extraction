import sys, numpy as np, collections, re
sys.path.insert(0, 'src'); sys.path.insert(0, '.')
import cache_eng
RX = re.compile(rb'[\x20-\x7e]{3,}')
f, eng, seq = sys.argv[1], sys.argv[2], int(sys.argv[3])
data, db, pts, cs, lay, M = cache_eng.get(f, eng)
m = next(x for x in M if x['seq'] == seq)
print('member', m['prof'], 'O', np.round(m['O'], 2), 'x', np.round(m['x'], 4), 'y', np.round(m['y'], 4), 'L', round(m['L'], 2))
r69 = db.bystride[69]
sel = r69[db.I(r69 + 17) == seq]
def dump(o, S, tag):
    D = [(k, round(float(db.D([o + k])[0]), 4)) for k in range(9, S - 7) if np.isfinite(db.D([o + k])[0]) and 1e-4 < abs(db.D([o + k])[0]) < 1e7]
    print(f'   {tag} off {o} stride {S} ints {[int(x) for x in db.I(o + np.arange(9, min(S, 120) - 3, 4))]}')
    print(f'      doubles {D[:24]}')
    strs = [(mm.start(), mm.group().decode('latin1')) for mm in RX.finditer(db.b[o:o + S])][:8]
    print('      strs', strs)
for o in sel:
    t = int(db.I([o + 13])[0]); ch = int(db.I([o + 21])[0])
    print('rel type', t, 'child', ch)
    for S, (K, O) in db.seqidx.items():
        lo, hi = np.searchsorted(K, ch, 'left'), np.searchsorted(K, ch, 'right')
        for oo in O[lo:hi][:3]: dump(int(oo), S, f'child rec')
