import sys, json, re, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
db,pts,cs,lay=decode('pairs/data/8.53_0575f7270f.db1',L['8.53']['layout'],V,False)
b=db.b
print('layout', {k:lay[k] for k in lay if k in ('stride','xyz','p1','p2','csys','attr','attr_stride','rest_ref')})
def refs(v):
    pat=int(v).to_bytes(4,'little',signed=True); out=[]; p=b.find(pat)
    while p>=0 and len(out)<20: out.append(p); p=b.find(pat,p+1)
    return out
for moff in (47763892, 47763965):
    print('== member', moff, 'stride', lay['stride'])
    for f in range(0, lay['stride'], 4 if False else 1):
        pass
    fields={f:int(db.I([moff+f])[0]) for f in (0,4,9,13,17,21,25,29,33,37)}
    print(fields)
for v in (42963621, 42963386):
    hs=refs(v); print('refs to',v, hs)
    for h in hs:
        # find the record containing h: nearest header before h in detected runs
        st=None
        for s,recs in db.bystride.items():
            i=np.searchsorted(recs,h,'right')-1
            if i>=0 and recs[i]<=h<recs[i]+s: st=(s,int(recs[i]),h-int(recs[i]))
        print('   at',h,'record(stride,start,field)=',st)
