import sys, json, pickle, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
from db1step import section_for
cat=json.load(open('catalog/tekla_profiles.json'))
L=json.load(open('layouts.json')); variants=[v['layout'] for v in L.values() if v.get('layout')]
tag, eng = sys.argv[1], sys.argv[2]
PL=[p for p in pickle.load(open(f'pairs/data/{tag}.ifc.plates.pkl','rb')) if p['cls']=='IfcPlate']
db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L[eng]['layout'],variants,False)
M=members(db,pts,cs,lay)
Os=np.array([m['O'] for m in M]); Es=np.array([m['E'] for m in M])
c=collections.Counter(); shown=0
for p in PL:
    mid=p['pts'][:-1]+p['n']*p['t']/2; cen=mid.mean(0)
    d=np.minimum(np.linalg.norm(Os-cen,axis=1),np.linalg.norm(Es-cen,axis=1)); j=np.argsort(d)[:3]
    # does any member have O or E exactly on a mid-plane vertex or edge midpoint?
    near=[(M[k]['prof'],round(float(d[k]),1),M[k]['cut'],section_for(M[k]['prof'],cat)[1] if section_for(M[k]['prof'],cat)[0] is None else section_for(M[k]['prof'],cat)[0]) for k in j]
    c[near[0][3] if near[0][1]<400 else 'far']+=1
    if shown<8: shown+=1; print(p['prof'],'t',round(p['t'],2),'size',np.round(np.ptp(mid,0),1),'| nearest members',near)
print(c.most_common())
