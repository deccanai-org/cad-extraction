import sys, json, collections, numpy as np, re
sys.path.insert(0, 'src')
from db1dec import *
f = sys.argv[1]
data = load(f); db = Db(data); db.segment()
recs = db.bystride[61]
v1 = np.stack([db.D(recs + 9 + 8 * i) for i in range(3)], 1); v2 = np.stack([db.D(recs + 33 + 8 * i) for i in range(3)], 1)
print(v1[:3], v2[:3])
print('norm1', np.abs((v1*v1).sum(1)-1)[:5], 'norm2', np.abs((v2*v2).sum(1)-1)[:5], 'dot', (v1*v2).sum(1)[:5])
print('ortho frac', Db._orthonormal(v1, v2).mean())
runs61 = [(s, r) for s, r in db.runs if s == 61]; print('runs of 61', len(runs61), [len(r) for s, r in runs61][:20])
for s, r in runs61[:3]:
    a = np.stack([db.D(r[:48] + 9 + 8 * i) for i in range(3)], 1); b = np.stack([db.D(r[:48] + 33 + 8 * i) for i in range(3)], 1)
    print(' run ortho', Db._orthonormal(a, b).mean())
