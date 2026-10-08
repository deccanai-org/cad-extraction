import sys, numpy as np
sys.path.insert(0, '/opt/db1v2/src3')
from db1dec import *
db = Db(load('/opt/db1v2/pairs/8.07_b638835644.db1')); db.segment()
p = 54567903
# which run holds p?
for s, recs in db.runs:
    i = np.searchsorted(recs, p, side='right') - 1
    if i >= 0 and recs[i] <= p < recs[i] + s:
        o = int(recs[i]); print('run stride', s, 'record', o, 'field +', p - o, 'n recs', len(recs)); break
else:
    o = None; print('not inside a detected run')
base = o if o is not None else p - 200
f = db.F(base + np.arange(0, 400, 4)); ii = db.I(base + np.arange(0, 400, 4))
for k in range(0, 100):
    print(f'+{4*k:3d} int={int(ii[k]):>12} f32={float(f[k]):.3f}' if abs(f[k]) < 1e6 else f'+{4*k:3d} int={int(ii[k]):>12}', end=' | ' if k % 4 != 3 else '\n')
