import sys, json, pickle, collections, numpy as np; sys.path.insert(0,'src')
exec(open('src/plate_e2e.py').read().split('truth = ')[0])
from db1dec import *
tag, eng, want = sys.argv[1], sys.argv[2], int(sys.argv[3])
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L[eng]['layout'],V,False)
M=[m for m in members(db,pts,cs,lay) if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
truth=[p for p in pickle.load(open(f'pairs/data/{tag}.ifc.plates.pkl','rb')) if p['cls']=='IfcPlate']
mids=[p['pts'][:-1] + p['n']/np.linalg.norm(p['n'])*p['t']/2 for p in truth]
own=np.concatenate([[i]*len(q) for i,q in enumerate(mids)]); tt=cKDTree(np.concatenate(mids))
def rec(m):
    r = int(db.lookup([int(db.I([m['off'] + lay['poly_field']])[0])], lay['poly_stride'])[0])
    if r >= 0 and lay.get('poly_field2'):
        r = int(db.lookup([int(db.I([r + lay['poly_field2']])[0])], lay['poly_stride2'])[0])
    return r
shown=0; seen=set()
for m in M:
    r=rec(m); P=db.polygon(lay,m)
    if r<0 or not P: continue
    n=len(P); typ=[int(x) for x in db.I(r+221+4*np.arange(n))]
    if want not in typ: continue
    Q=np.array([m['O']+m['x']*a+m['y']*b for a,b in P])
    d,j=tt.query(Q); hits=[own[k] for k,dd in zip(j,d) if dd<0.5]
    if len(hits)<1: continue
    ti=collections.Counter(hits).most_common(1)[0][0]
    key=(tuple(typ), tuple(np.round(P,0).ravel()))
    if key in seen: continue
    seen.add(key)
    cx=[round(float(x),2) for x in db.F(r+141+4*np.arange(n))]; cy=[round(float(x),2) for x in db.F(r+181+4*np.arange(n))]
    w=[round(float(x),2) for x in db.F(r+101+4*np.arange(n))]
    uv=[(round(float((q-m['O'])@m['x']),1), round(float((q-m['O'])@m['y']),1)) for q in mids[ti]]
    print('ours',[(round(a,1),round(b,1)) for a,b in P],'types',typ,'cx',cx,'cy',cy,'w',w,'\n   truth',len(uv),uv)
    shown+=1
    if shown>=6: break
