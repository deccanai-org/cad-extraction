"""rec_dump.py KITDIR DB1 ID... : live records (prefix 4) whose first int is ID: ints and doubles at every alignment"""
import sys, os, re, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old
from db1dec import load
data = load(sys.argv[2]); o = db1old.Old(data); I = o.I_all; D = o.D_all; N = len(I) - 400
def fd(v): return round(float(v), 4) if np.isfinite(v) and abs(v) < 1e7 and (v == 0 or abs(v) > 1e-6) else None
for i in map(int, sys.argv[3:]):
    recs = [int(q) for q in np.nonzero(I[8:N] == i)[0] + 8 if data[int(q) - 1] == 4]
    print('== id', i, 'live records at', recs[:6])
    for q in recs[:3]:
        print('   @%d ints %s' % (q, [int(I[q + 4 * k]) for k in range(24)]))
        for al in (4, 8):
            print('      dbl@+%d %s' % (al, [fd(D[q + al + 8 * k]) for k in range(12)]))
