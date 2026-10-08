import sys, json, glob, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
import db1dec
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
for f in sorted(glob.glob('pairs/data/ag_*.db1')):
    e=f.split('_')[1]; db,pts,cs,lay=decode(f,L[e]['layout'],V,True); M=members(db,pts,cs,lay); P=pts[lay['pts']]
    offs=np.array([m['off'] for m in M]); X=np.array([m['xr'] for m in M])
    p1=db._pt(P,db.I(offs+lay['p1'])); p2=db._pt(P,db.I(offs+lay['p2'])); d=p2-p1; n=np.linalg.norm(d,axis=1)
    ok=n>1; ang=np.degrees(np.arccos(np.clip(np.abs((d[ok]/n[ok,None]*X[ok]).sum(1)),0,1)))
    bad=ang>np.degrees(np.arccos(0.999))
    h=collections.Counter(('<5' if a<5 else '5-15' if a<15 else '15-45' if a<45 else '45-85' if a<85 else '85-90') for a in ang[bad])
    names=collections.Counter(m['prof'] for m,b in zip([m for m,o in zip(M,ok) if o], bad) if b).most_common(4)
    print(f.split('/')[-1], 'members', len(M), 'disagree', int(bad.sum()), 'angle hist', dict(h), names)
