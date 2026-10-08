import sys, json, re, pickle, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
tag='8.53_0575f7270f'
PL=[p for p in pickle.load(open(f'pairs/data/{tag}.ifc.plates.pkl','rb')) if p['cls']=='IfcPlate']
db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L['8.53']['layout'],V,False)
M=members(db,pts,cs,lay)
b=db.b; N=len(b); print('raw bytes',N)
Fa=[np.frombuffer(b,'<f4',count=(N-k)//4,offset=k) for k in range(4)]
cp=[m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
Os=np.array([m['O'] for m in cp])
def search(us, tol=0.06):
    """positions p (byte offsets) where float32 at p+4i ~ us[i] for all i"""
    out=[]
    for k in range(4):
        F=Fa[k]; n=len(F)-len(us)
        ok=np.abs(F[:n]-us[0])<tol
        for i in range(1,len(us)):
            idx=np.nonzero(ok)[0]
            ok2=np.abs(F[idx+i]-us[i])<tol; ok=np.zeros(n,bool); ok[idx[ok2]]=True
        out+= [int(k+4*j) for j in np.nonzero(ok)[0]]
    return sorted(out)
res=[]; done=0
for p in PL[:400]:
    mid=p['pts'][:-1]+p['n']*p['t']/2
    for vtx in mid:
        dd=np.linalg.norm(Os-vtx,axis=1); j=int(np.argmin(dd))
        if dd[j]>1: continue
        m=cp[j]; uv=[((q-m['O'])@m['x'],(q-m['O'])@m['y']) for q in mid]
        k0=int(np.argmin([abs(a)+abs(c) for a,c in uv])); uv=uv[k0:]+uv[:k0]
        if len(uv)<5: break
        for d,seq in (('fwd',uv),('rev',[uv[0]]+uv[1:][::-1])):
            us=[a for a,c in seq][:5]
            if sum(abs(x)>1 for x in us)<3: continue
            hits=search(us)
            if hits: res.append((m,seq,d,hits)); break
        break
    if len(res)>=12: break
print('found',len(res))
for m,seq,d,hits in res[:12]:
    print(m['prof'], round(m['L'],1), d, [ (round(a,1),round(c,1)) for a,c in seq], 'hits',hits[:4], 'moff',m['off'])
pickle.dump([(m['off'],seq,d,hits) for m,seq,d,hits in res],open('/tmp/re853.pkl','wb'))
