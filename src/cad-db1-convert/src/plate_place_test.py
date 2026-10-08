import sys, json, pickle, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); variants=[v['layout'] for v in L.values() if v.get('layout')]
tag, eng, field = sys.argv[1], sys.argv[2], int(sys.argv[3])
PL=[p for p in pickle.load(open(f'pairs/data/{tag}.ifc.plates.pkl','rb')) if p['cls']=='IfcPlate']
db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L[eng]['layout'],variants,False)
M=members(db,pts,cs,lay)
cp=[m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
def outline(o,cap=10):
    u=db.F(o+21+4*np.arange(cap)).astype(float); v=db.F(o+61+4*np.arange(cap)).astype(float)
    k=1
    while k<cap and not (abs(u[k])<1e-3 and abs(v[k])<1e-3): k+=1
    return u[:k],v[:k]
# IFC plate vertex sets (mid-plane), as a KD-ish lookup by rounding
ifcV=[p['pts'][:-1]+p['n']*p['t']/2 for p in PL]
allv=np.concatenate(ifcV) if ifcV else np.zeros((0,3))
res=collections.Counter()
for m in cp:
    rec=None
    for o in db.lookup_all(int(db.I([m['off']+field])[0]),341)[:3]:
        u,v=outline(o)
        if len(u)>=3 and abs((u.max()-u.min())-m['L'])<0.05: rec=(u,v); break
    if rec is None: res['no_outline']+=1; continue
    u,v=rec
    variants_={}
    for name,(uu,vv) in {'raw':(u,v),'u-umin':(u-u.min(),v),'u-umin,v-vmin':(u-u.min(),v-v.min())}.items():
        for sx in (1,-1):
            for sy in (1,-1):
                xa = m['x'] if sx==1 else -m['x']
                P=[m['O']+xa*a+sy*m['y']*b for a,b in zip(uu,vv)]
                ok=all(np.min(np.linalg.norm(allv-q,axis=1))<1.0 for q in P)
                if ok: variants_[f'{name} x{sx:+d} y{sy:+d}']=1
    res[tuple(sorted(variants_)) or ('none',)]+=1
for k,v in res.most_common(8): print(v,k)
