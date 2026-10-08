import sys, json, pickle, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
tag, eng = sys.argv[1], sys.argv[2]
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L[eng]['layout'],V,False)
M=[m for m in members(db,pts,cs,lay) if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
def rec(m):
    r = int(db.lookup([int(db.I([m['off'] + lay['poly_field']])[0])], lay['poly_stride'])[0])
    if r >= 0 and lay.get('poly_field2'):
        r = int(db.lookup([int(db.I([r + lay['poly_field2']])[0])], lay['poly_stride2'])[0])
    return r
pat=collections.Counter(); ex={}
for m in M:
    r=rec(m); P=db.polygon(lay,m)
    if r<0 or not P: continue
    n=len(P); typ=tuple(int(x) for x in db.I(r+221+4*np.arange(n)))
    if 20 not in typ: continue
    cx=tuple(round(float(x),2) for x in db.F(r+141+4*np.arange(n))); cy=tuple(round(float(x),2) for x in db.F(r+181+4*np.arange(n)))
    pat[typ]+=1
    ex.setdefault(typ,[]).append((m['prof'], [(round(a,1),round(b,1)) for a,b in P], cx, cy, [round(c,1) for c in m['O']]))
print(pat.most_common(10))
for t,v in list(ex.items())[:5]:
    for e in v[:2]: print(t, e)
