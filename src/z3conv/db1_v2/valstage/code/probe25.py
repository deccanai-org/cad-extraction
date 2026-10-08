import sys, numpy as np, collections, re
from cache import *
db1 = sys.argv[1]; keys = [int(x) for x in sys.argv[2:]]
db, pts, cs, lay, M = get(db1)
for k in keys:
    for s, (K, O) in db.seqidx.items():
        lo, hi = np.searchsorted(K, k, 'left'), np.searchsorted(K, k, 'right')
        for o in O[lo:hi][:2]:
            o = int(o); raw = db.b[o:o + s]
            print(k, 'stride', s, 'off', o)
            print('   ints', [(j, int(x)) for j, x in zip(range(9, s - 3, 4), db.I(o + np.arange(9, s - 3, 4)))][:30])
            print('   floats', [(j, round(float(x), 3)) for j, x in zip(range(9, s - 3), db.F(o + np.arange(9, s - 3))) if np.isfinite(x) and 0.01 < abs(x) < 1e6 and abs(x * 100 - round(x * 100)) < 1e-3][:40])
            print('   strs', [(mm.start(), mm.group().decode('latin1')) for mm in re.finditer(rb'[\x20-\x7e]{3,}', raw)][:12])
