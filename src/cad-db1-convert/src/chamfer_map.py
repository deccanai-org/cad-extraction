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
maps=collections.Counter(); ex=[]
for p in truth:
    mid = p['pts'][:-1] + p['n']/np.linalg.norm(p['n'])*p['t']/2
    dm, jm = otree.query(mid); i=int(np.argmin(dm))
    if dm[i] >= 1.0: continue
    m=M[jm[i]]; P=db.polygon(lay,m); r=rec(m)
    if not P or r<0: continue
    n=len(P); typ=[int(x) for x in db.I(r+221+4*np.arange(n))]; cx=[float(x) for x in db.F(r+141+4*np.arange(n))]
    if not any(typ): continue
    uv=np.array([((q-m['O'])@m['x'], (q-m['O'])@m['y']) for q in mid])
    absent=[j for j,(a,b) in enumerate(P) if np.min(np.hypot(uv[:,0]-a, uv[:,1]-b))>0.5]
    ch=[j for j in range(n) if typ[j]]
    # which index maps explain it
    fits=[]
    for name,f in (('same',lambda j:j),('rev',lambda j:(n-1-j)%n),('rev+1',lambda j:(1-j)%n),('rev+2',lambda j:(2-j)%n),('shift+1',lambda j:(j+1)%n),('shift-1',lambda j:(j-1)%n)):
        if sorted(f(j) for j in ch)==sorted(absent): fits.append(name)
    maps[(n,tuple(fits))]+=1
    if len(ex)<6: ex.append((n, [ (round(a,1),round(b,1)) for a,b in P], 'types',typ,'cx',[round(c,1) for c in cx],'absent',absent,'truth',[(round(a,1),round(b,1)) for a,b in uv]))
print(maps.most_common(20))
for e in ex: print(e)
