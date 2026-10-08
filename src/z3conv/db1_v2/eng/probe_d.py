import sys, json, collections, numpy as np, re
sys.path.insert(0, 'src')
from db1dec import *
f = sys.argv[1]
data = load(f); db = Db(data); db.segment()
for s in (61, 64, 33, 29, 17, 21, 54, 49):
    recs = db.bystride.get(s)
    if recs is None: continue
    print('stride', s, len(recs))
    for o in recs[:3]:
        D = db.D(o + np.arange(9, s - 7)); I = db.I(o + np.arange(9, s - 3, 4))
        print('   ints', [int(x) for x in I][:16])
        print('   dbl@k', [(k + 9, round(float(x), 4)) for k, x in enumerate(D) if np.isfinite(x) and 1e-6 < abs(x) < 1e7 and abs(x * 1e4 - round(x * 1e4)) < 1e-3][:12])
r = db.bystride[73]; I = db.I(r[:5, None] + np.arange(9, 73, 4)[None, :]); print('73 ints', I.tolist())
cs = db.find_csys(); print('csys candidates', [(c['stride'], c['k'], c['key'], len(c['keys'])) for c in cs])
