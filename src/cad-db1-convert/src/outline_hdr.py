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
c=collections.Counter(); ex=[]
S=lay.get('poly_stride2') or lay['poly_stride']
for m in M:
    r=rec(m)
    if r<0: continue
    u=db.F(r+21+4*np.arange(10)); v=db.F(r+61+4*np.arange(10))
    n=1
    while n<10 and not (abs(u[n])<1e-3 and abs(v[n])<1e-3): n+=1
    h13=int(db.I([r+13])[0]); h17=int(db.I([r+17])[0])
    typ=[int(x) for x in db.I(r+221+4*np.arange(10))]
    sent=typ.index(2147483647) if 2147483647 in typ else -1
    c[(n, h13, h17 if h17<100 else 'big', sent)]+=1
print(sorted(c.items(), key=lambda kv:-kv[1])[:30])
print('--- 10-vertex records')
k=0
for m in M:
    r=rec(m)
    if r<0: continue
    typ=[int(x) for x in db.I(r+221+4*np.arange(10))]
    u=db.F(r+21+4*np.arange(10)); v=db.F(r+61+4*np.arange(10))
    if 2147483647 in typ or abs(u[9])+abs(v[9])<1e-3: continue
    print('rec',r,'objid',int(db.I([r])[0]),'ref',int(db.I([r+4])[0]),'seq',int(db.I([r+9])[0]),'h13',int(db.I([r+13])[0]),'h17',int(db.I([r+17])[0]),'L',round(m['L'],1))
    print('   u',[round(float(x),1) for x in u]); print('   v',[round(float(x),1) for x in v])
    for nb in (r+S, r-S):
        print('   nb',nb,'objid',int(db.I([nb])[0]),'ref',int(db.I([nb+4])[0]),'seq',int(db.I([nb+9])[0]),'h13',int(db.I([nb+13])[0]),'u',[round(float(x),1) for x in db.F(nb+21+4*np.arange(10))][:6])
    # anything else referencing this record's objid/seq?
    for val in (int(db.I([r])[0]), int(db.I([r+9])[0])):
        pat=val.to_bytes(4,'little',signed=True); hits=[]; p=db.b.find(pat)
        while p>=0 and len(hits)<8: hits.append(p-r); p=db.b.find(pat,p+1)
        print('   refs to',val,'rel offsets',hits)
    k+=1
    if k>=3: break
