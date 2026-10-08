import sys, json, pickle, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
tag = sys.argv[1]
PL=[p for p in pickle.load(open(f'pairs/data/{tag}.ifc.plates.pkl','rb')) if p['cls']=='IfcPlate']
db=Db(load(f'pairs/data/{tag}.db1')); db.segment()
b=db.b; L=len(b)
arrs=[np.frombuffer(b[s:s+(L-s)//8*8],'<f8') for s in range(8)]
def find(v,tol=0.6):
    out=[]
    for sh,a in enumerate(arrs):
        m=np.nonzero(np.abs(a[:-2]-v[0])<tol)[0]
        for i in m:
            if abs(a[i+1]-v[1])<tol and abs(a[i+2]-v[2])<tol: out.append(sh+8*i)
    return out
def where(p):
    for s,recs in db.runs:
        i=np.searchsorted(recs,p,side='right')-1
        if i>=0 and recs[i]<=p<recs[i]+s: return (s,p-int(recs[i]))
    return None
c=collections.Counter(); n=0
for p in PL:
    face=p['pts'][:-1]; mid=face+p['n']*p['t']/2; top=face+p['n']*p['t']
    for nm,S in (('mid',mid),('face',face),('top',top)):
        hits=[h for q in S for h in find(q)]
        if hits:
            c[(nm,)+tuple(sorted({str(where(h)) for h in hits[:4]}))]+=1; break
    else: c['nowhere']+=1
    n+=1
    if n>=40: break
for k,v in c.most_common(10): print(v,k)
