import sys, json, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
for tag, eng in [a.split(':') for a in sys.argv[1:]]:
    db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L[eng]['layout'],V,False)
    if not lay.get('poly_stride'): print(tag,'no poly'); continue
    S=lay.get('poly_stride2') or lay['poly_stride']; ub=lay['poly_ub']; cap=lay['poly_cap']
    recs=db.bystride.get(S, np.zeros(0,np.int64))
    T=np.stack([db.I(recs+ub+4*cap*5+4*i) for i in range(cap)],1)
    c=collections.Counter(int(x) for x in T.ravel()); W=np.stack([db.F(recs+ub+4*cap*2+4*i) for i in range(cap)],1)
    D1=np.stack([db.F(recs+ub+4*cap*6+4*i) for i in range(cap)],1); D2=np.stack([db.F(recs+ub+4*cap*7+4*i) for i in range(cap)],1)
    print(tag, 'records', len(recs), 'type codes', c.most_common(12), '|w|>0.01:', int((np.abs(W)>0.01).any(1).sum()), 'dz!=0:', int(((np.abs(D1)>0.01)|(np.abs(D2)>0.01)).any(1).sum()),
          'h13 dist', collections.Counter(int(x) for x in db.I(recs+13)).most_common(5))
