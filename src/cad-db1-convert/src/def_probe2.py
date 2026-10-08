import sys, json, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
f=sys.argv[1]; db=Db(load(f)); db.segment()
for S in [int(x) for x in sys.argv[2].split(',')]:
    recs=db.bystride.get(S)
    if recs is None: continue
    print('== stride', S, 'records', len(recs))
    for o in recs[len(recs)//2: len(recs)//2+3]:
        o=int(o)
        dd=[round(float(x),4) for x in db.D(o+13+np.arange(0,S-13-7,8))]
        print('  hdr', [int(x) for x in db.I(np.array([o,o+4,o+9]))], 'D@13..', dd[:8])
        for k in range(9, S-47):
            v=db.D(o+k+np.arange(0,48,8))
            if np.all(np.isfinite(v)) and abs(np.linalg.norm(v[:3])-1)<1e-6 and abs(np.linalg.norm(v[3:])-1)<1e-6:
                print('    unit vector pair at +%d'%k, [round(float(x),4) for x in v])
