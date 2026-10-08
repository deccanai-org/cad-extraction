import sys, json, re, struct, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); variants=[v['layout'] for v in L.values() if v.get('layout')]
db,pts,cs,lay=decode(sys.argv[1],L[sys.argv[2]]['layout'],variants,False)
M=members(db,pts,cs,lay)
cp=[m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
print('contour plates',len(cp),'member stride',lay['stride'])
def outline(o,cap=10):
    u=db.F(o+21+4*np.arange(cap)); v=db.F(o+61+4*np.arange(cap))
    k=1
    while k<cap and not (abs(u[k])<1e-3 and abs(v[k])<1e-3): k+=1
    return u[:k],v[:k]
res=collections.Counter()
for f in range(9,lay['stride']-3):
    ok=0; n=0
    for m in cp[:300]:
        val=int(db.I([m['off']+f])[0]); n+=1
        for o in db.lookup_all(val,341)[:3]:
            u,v=outline(o)
            if len(u)>=3 and abs((u.max()-u.min())-m['L'])<0.05: ok+=1; break
    if ok: res[f]=(ok,n)
print('field -> plates whose 341-record outline u-extent == L:',dict(res))
# same-key (member seq) lookup
ok=0
for m in cp[:300]:
    seq=int(db.I([m['off']+9])[0])
    for o in db.lookup_all(seq,341)[:3]:
        u,v=outline(o)
        if len(u)>=3 and abs((u.max()-u.min())-m['L'])<0.05: ok+=1; break
print('same seq key:',ok,'/',min(300,len(cp)))
