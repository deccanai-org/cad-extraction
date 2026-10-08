import sys, json, re, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
db,pts,cs,lay=decode('pairs/data/8.53_0575f7270f.db1',L['8.53']['layout'],V,False)
b=db.b
def rec(o,s): return {f:int(db.I([o+f])[0]) for f in range(0,s-3,4 if s<0 else 1) if f in (0,4,9,13,17,21,25,29)}
for o in (47073310, 47073343):
    print('s33', o, rec(o,33))
def refs(v):
    pat=int(v).to_bytes(4,'little',signed=True); out=[]; p=b.find(pat)
    while p>=0 and len(out)<20: out.append(p); p=b.find(pat,p+1)
    return out
def where(h):
    for s,recs in db.bystride.items():
        i=np.searchsorted(recs,h,'right')-1
        if i>=0 and recs[i]<=h<recs[i]+s: return (s,int(recs[i]),h-int(recs[i]))
for o in (47073310, 47073343):
    for f in (0,9):
        v=int(db.I([o+f])[0]); print(' refs to s33 field',f,v,[ (h,where(h)) for h in refs(v)])
# the member's +29 target
for moff in (47763892, 47763965):
    for f in (9,17,21,25,29,33):
        v=int(db.I([moff+f])[0]); r=db.lookup([v])[0]; st=db.lookup_stride([v])[0]
        print('member',moff,'+%d'%f,v,'-> stride',st,'rec',r, rec(int(r),int(st)) if r>=0 else None)
