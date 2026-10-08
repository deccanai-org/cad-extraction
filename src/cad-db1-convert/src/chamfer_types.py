import sys, json, pickle, collections, numpy as np; sys.path.insert(0,'src')
exec(open('src/plate_e2e.py').read().split('truth = ')[0])
from db1dec import *
tag, eng = sys.argv[1], sys.argv[2]
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L[eng]['layout'],V,False)
M=[m for m in members(db,pts,cs,lay) if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
truth=[p for p in pickle.load(open(f'pairs/data/{tag}.ifc.plates.pkl','rb')) if p['cls']=='IfcPlate']
Os=np.array([m['O'] for m in M]); otree=cKDTree(Os)
def rec(m):
    r = int(db.lookup([int(db.I([m['off'] + lay['poly_field']])[0])], lay['poly_stride'])[0])
    if r >= 0 and lay.get('poly_field2'):
        r = int(db.lookup([int(db.I([r + lay['poly_field2']])[0])], lay['poly_stride2'])[0])
    return r
tc=collections.Counter(); ex=collections.defaultdict(list)
for m in M:
    r=rec(m); P=db.polygon(lay,m)
    if r<0 or not P: continue
    n=len(P)
    for j in range(n):
        t=int(db.I([r+221+4*j])[0])
        if t: 
            x=float(db.F([r+141+4*j])[0]); y=float(db.F([r+181+4*j])[0]); d1=float(db.F([r+261+4*j])[0]); d2=float(db.F([r+301+4*j])[0]); w=float(db.F([r+101+4*j])[0])
            tc[(t, x==y, d1!=0 or d2!=0, w!=0)]+=1
print('chamfer (type, x==y, dz!=0, w!=0):', tc.most_common(30))
# per type: truth geometry around a chamfered vertex for x!=y cases
shown=collections.Counter()
for p in truth:
    mid = p['pts'][:-1] + p['n']/np.linalg.norm(p['n'])*p['t']/2
    dm, jm = otree.query(mid); i=int(np.argmin(dm))
    if dm[i] >= 1.0: continue
    m=M[jm[i]]; P=db.polygon(lay,m); r=rec(m)
    if not P or r<0: continue
    n=len(P)
    for j in range(n):
        t=int(db.I([r+221+4*j])[0])
        if not t: continue
        x=float(db.F([r+141+4*j])[0]); y=float(db.F([r+181+4*j])[0])
        key=(t, abs(x-y)>0.01)
        if shown[key]>=2: continue
        shown[key]+=1
        uv=[(round(float((q-m['O'])@m['x']),1), round(float((q-m['O'])@m['y']),1)) for q in mid]
        print('type',t,'x',round(x,2),'y',round(y,2),'vertex',j,'of',[(round(a,1),round(b,1)) for a,b in P],'\n    truth',uv)
