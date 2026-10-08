import sys, json, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
tag, eng = sys.argv[1], sys.argv[2]
db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L[eng]['layout'],V,False)
M=members(db,pts,cs,lay)
seq=lambda m:int(db.I([m['off']+9])[0])
cuts=[m for m in M if m['cut']]; parts=[m for m in M if not m['cut']]
cut_seq={seq(m) for m in cuts}; part_seq={seq(m) for m in parts}
print('cuts',len(cuts),'parts',len(parts))
# scan every run: records containing a cut seq AND a part seq in int fields
hits=collections.Counter(); ex={}
for s,recs in db.runs:
    if s>200 or len(recs)<3: continue
    for f1 in range(9,s-3,1):
        v1=db.I(recs+f1)
        m1=np.isin(v1,list(cut_seq))
        if m1.sum()<5: continue
        for f2 in range(9,s-3,1):
            if f2==f1: continue
            v2=db.I(recs+f2)
            m2=m1&np.isin(v2,list(part_seq))
            if m2.sum()>=5:
                hits[(s,f1,f2)]+=int(m2.sum())
                ex.setdefault((s,f1,f2),[int(x) for x in db.I(recs[m2][0]+np.arange(0,s-3,4))])
for k,v in hits.most_common(8): print(k,v,ex[k][:10])
