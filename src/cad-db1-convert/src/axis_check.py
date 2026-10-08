import sys, json, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
for tag, eng in [a.split(':') for a in sys.argv[1:]]:
    db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L[eng]['layout'],V,False)
    M=members(db,pts,cs,lay); P=pts[lay.get('pts',0)]
    offs=np.array([m['off'] for m in M]); X=np.array([m['xr'] for m in M])
    p1=db._pt(P, db.I(offs+lay['p1'])); p2=db._pt(P, db.I(offs+lay['p2'])); d=p2-p1; n=np.linalg.norm(d,axis=1); ok=np.isfinite(n)&(n>1)
    ag=np.abs((d[ok]/n[ok,None]*X[ok]).sum(1))>0.999
    kinds=collections.Counter(); bad=collections.Counter()
    for m,a in zip([m for m,o in zip(M,ok) if o], ag):
        k='plate' if (m['prof'] and PLATE1_RE.match(m['prof'])) else ('cut' if m['cut'] else ('noprof' if not m['prof'] else 'beam'))
        kinds[k]+=1
        if not a: bad[k]+=1
    print(tag, 'csys', lay['csys'], lay['csys_key'], 'agreement', round(float(ag.mean()),4), 'n', int(ok.sum()), 'disagree by kind', dict(bad), 'of', dict(kinds))
