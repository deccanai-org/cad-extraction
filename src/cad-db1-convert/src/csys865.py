import sys, json, time, collections, numpy as np; sys.path.insert(0,'src')
import db1dec
from db1dec import *
L=json.load(open('layouts.json')); base=dict(L[sys.argv[2]]['layout'])
db=Db(load(sys.argv[1])); db.segment()
pts=db.find_points(fixed=(base['pts_stride'],base['pts_k']))
cs=db.find_csys(only=(base.get('csys_stride') or 61, base.get('csys_k') or 9))
recs=db.bystride.get(base['stride']); db._member_run=recs
out={}
for f in (29,33,37,41-4):
    for ci,C in enumerate(cs):
        trial=dict(stride=base['stride'], xyz=base['xyz'], pts=0, p1=base['p1'], p2=base['p2'], csys=f, csys_key=C['key'], csys_stride=C['stride'], csys_k=C['k'])
        M=members(db,pts,cs,trial)
        if not M: continue
        out[(f,C['key'])]={m['off']:m for m in M}
        print('csys',f,C['key'],'members',len(M),'webvert',db1dec._web_vertical(M))
ks=list(out)
for i in range(len(ks)):
    for j in range(i+1,len(ks)):
        A,B=out[ks[i]],out[ks[j]]; common=set(A)&set(B)
        if not common: continue
        agree=sum(1 for o in common if abs(A[o]['x']@B[o]['x'])>0.999 and abs(A[o]['y']@B[o]['y'])>0.999)
        print(ks[i],ks[j],'common',len(common),'same frame',agree)
P=pts[0]
for k,Md in out.items():
    offs=np.array(list(Md)); p1=db._pt(P, db.I(offs+base['p1'])); p2=db._pt(P, db.I(offs+base['p2']))
    d=p2-p1; n=np.linalg.norm(d,axis=1); ok=n>1
    X=np.array([Md[o]['xr'] for o in offs])
    ag=np.abs((d[ok]/n[ok,None]*X[ok]).sum(1))
    print(k,'axis agreement |x.(p2-p1)|>0.999:', round(float(np.mean(ag>0.999)),3), 'n', int(ok.sum()))
print('base layout csys', base.get('csys'), base.get('csys_key'))
