import sys, json, pickle, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); variants=[v['layout'] for v in L.values() if v.get('layout')]
tag, eng = sys.argv[1], sys.argv[2]
PL=[p for p in pickle.load(open(f'pairs/data/{tag}.ifc.plates.pkl','rb')) if p['cls']=='IfcPlate']
db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L[eng]['layout'],variants,False)
M=members(db,pts,cs,lay)
Os=np.array([m['O'] for m in M]); Es=np.array([m['E'] for m in M])
res=collections.Counter(); ex=[]
for p in PL:
    face=p['pts'][:-1]; mid=face+p['n']*p['t']/2; top=face+p['n']*p['t']
    hit=None
    for nm,S in (('mid',mid),('face',face),('top',top)):
        for q in S:
            d=np.linalg.norm(Os-q,axis=1); j=int(np.argmin(d))
            if d[j]<1: hit=(nm,'O',j); break
            d=np.linalg.norm(Es-q,axis=1); j=int(np.argmin(d))
            if d[j]<1: hit=(nm,'E',j); break
        if hit: break
    if hit:
        m=M[hit[2]]; res[(hit[0],hit[1],m['prof'][:2] if m['prof'] else None,bool(m['cut']))]+=1
        if len(ex)<4 and m['prof'] and not m['prof'].startswith('PL'): ex.append((p['prof'],m['prof'],round(m['L'],1)))
    else: res['no member at any corner']+=1
print(res.most_common(10)); print(ex)
