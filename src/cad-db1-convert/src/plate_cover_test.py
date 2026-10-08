import sys, json, pickle, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
from db1step import section_for
cat=json.load(open('catalog/tekla_profiles.json'))
L=json.load(open('layouts.json')); variants=[v['layout'] for v in L.values() if v.get('layout')]
tag, eng, field = sys.argv[1], sys.argv[2], int(sys.argv[3])
PL=[p for p in pickle.load(open(f'pairs/data/{tag}.ifc.plates.pkl','rb')) if p['cls']=='IfcPlate']
db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L[eng]['layout'],variants,False)
M=[m for m in members(db,pts,cs,lay) if not m['cut']]
def outline(o,cap=10):
    u=db.F(o+21+4*np.arange(cap)).astype(float); v=db.F(o+61+4*np.arange(cap)).astype(float)
    k=1
    while k<cap and not (abs(u[k])<1e-3 and abs(v[k])<1e-3): k+=1
    return u[:k],v[:k]
corners=[]   # (kind, array of solid corner points)
for m in M:
    if not m['prof']: continue
    k,v,how=section_for(m['prof'],cat)
    if k=='RECT':
        t,b=v[0],v[1]; xr,y=m['xr'],m['y']; px=np.cross(xr,y); A=m['O']+(xr*m['L'] if m['sgn']==1 else 0); e=-xr
        corners.append(('rect',np.array([A+e*s*m['L']+px*a*t/2+y*c*b/2 for s in (0,1) for a in (-1,1) for c in (-1,1)])))
    elif k is None and v=='contour_plate':
        for o in db.lookup_all(int(db.I([m['off']+field])[0]),341)[:3]:
            u,vv=outline(o)
            if len(u)>=3 and abs((u.max()-u.min())-m['L'])<0.05:
                t=float(re.findall(r'[\d.]+',m['prof'])[0]); n=np.cross(m['x'],m['y'])
                P=[m['O']+m['x']*a+m['y']*c for a,c in zip(u,vv)]
                corners.append(('contour',np.array([q+n*s*t/2 for q in P for s in (-1,1)]))); break
allc=np.concatenate([c for _,c in corners]); kinds=np.concatenate([[k]*len(c) for k,c in corners])
res=collections.Counter()
for p in PL:
    V=np.concatenate([p['pts'][:-1], p['pts'][:-1]+p['n']*p['t']])
    d=[np.min(np.linalg.norm(allc-q,axis=1)) for q in V]
    if max(d)<1.0:
        j=int(np.argmin(np.linalg.norm(allc-V[0],axis=1))); res['reproduced_by_'+kinds[j]]+=1
    else: res['not_reproduced']+=1
print(tag,'IfcPlate',len(PL),dict(res))
