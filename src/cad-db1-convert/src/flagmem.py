"""member-shaped records whose header flag byte is not 0x04 (missed by segment())"""
import sys, re, json, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
tag, eng = sys.argv[1], sys.argv[2]
L=json.load(open('layouts.json')); lay=dict(L[eng]['layout']); lay['pts']=0
db=Db(load(tag if tag.endswith('.db1') else f'pairs/data/{tag}.db1')); db.segment()
pts=db.find_points(fixed=(lay['pts_stride'],lay['pts_k'])); cs=db.find_csys(only=(lay['csys_stride'],lay['csys_k']))
C=[c for c in cs if c['key']==lay['csys_key']][0]
u8=db.u8; flags=collections.Counter(int(x) for x in u8[np.nonzero(np.isin(u8[8:-8], [1,2,3,5,6,7,8]))[0][:0]+8]) if False else None
res={}
for fl in (4,1,5,2,3,6,7,8,9,12):
    cand=np.nonzero(u8[8:db.L-lay['stride']]==fl)[0]
    a=db.I(cand); r=db.I(cand+4); cand=cand[(a>0)&(r>0)]
    k=lay['xyz']; X=np.stack([db.D(cand+k+8*i) for i in range(4)],1)
    P=pts[0]; p1=db._pt(P, db.I(cand+lay['p1'])); p2=db._pt(P, db.I(cand+lay['p2'])); cc=db.I(cand+lay['csys'])
    ok=(np.all(np.isfinite(X),1)&(X[:,3]>0)&(np.abs(X[:,:3])<1e8).all(1)&np.all(np.isfinite(p1),1)&np.all(np.isfinite(p2),1)&inkeys(C['keys'],cc))
    # length consistency |p2-p1| ~ L
    d=np.linalg.norm(p2-p1,axis=1); ok&=np.abs(d-X[:,3])<1.0
    res[fl]=int(ok.sum())
print(tag, 'member-shaped records by header flag byte:', res)
