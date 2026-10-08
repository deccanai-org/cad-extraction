import sys, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
f=sys.argv[1]; db=Db(load(f)); db.segment()
for s, recs in db.runs:
    if s != 61: continue
    smp=recs[:48]; k=9
    v1 = np.stack([db.D(smp + k + 8 * i) for i in range(3)], 1); v2 = np.stack([db.D(smp + k + 24 + 8 * i) for i in range(3)], 1)
    print('run len', len(recs), 'orthonormal', round(float(db._orthonormal(v1, v2).mean()),3), 'first', int(recs[0]))
print(len(db.find_csys()), len(db.find_csys(only=(61,9))))
