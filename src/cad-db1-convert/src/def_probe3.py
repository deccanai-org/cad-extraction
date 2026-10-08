import sys, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
f=sys.argv[1]; db=Db(load(f)); db.segment()
res=[]
for S, recs in db.bystride.items():
    if S < 40 or len(recs) < 50: continue
    smp=recs[:: max(1, len(recs)//300)][:300]
    for k in range(9, S-47):
        v=np.stack([db.D(smp+k+8*i) for i in range(6)],1)
        with np.errstate(invalid='ignore', over='ignore'):
            a=np.abs(np.linalg.norm(v[:,:3],axis=1)-1)<1e-4; b=np.abs(np.linalg.norm(v[:,3:],axis=1)-1)<1e-4
            orth=np.abs((v[:,:3]*v[:,3:]).sum(1))<1e-4
        fr=float(np.mean(a&b&orth))
        if fr>0.3: res.append((round(fr,2), S, k, len(recs)))
print(sorted(res, reverse=True)[:12])
# also float32 unit pairs
res=[]
for S, recs in db.bystride.items():
    if S < 30 or len(recs) < 50: continue
    smp=recs[:: max(1, len(recs)//300)][:300]
    for k in range(9, S-23):
        v=np.stack([db.F(smp+k+4*i) for i in range(6)],1)
        with np.errstate(invalid='ignore', over='ignore'):
            a=np.abs(np.linalg.norm(v[:,:3],axis=1)-1)<1e-3; b=np.abs(np.linalg.norm(v[:,3:],axis=1)-1)<1e-3
            orth=np.abs((v[:,:3]*v[:,3:]).sum(1))<1e-3
        fr=float(np.mean(a&b&orth))
        if fr>0.3: res.append((round(fr,2), S, k, len(recs)))
print('float32', sorted(res, reverse=True)[:12])
