import sys, re, json, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
f=sys.argv[1]
db,pts,cs,lay=decode(f, L['8.95']['layout'], V, False)
M=members(db,pts,cs,lay)
cp=[m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
print('contour plate members', len(cp))
b=db.b; N=len(b)
Fa=[np.frombuffer(b,'<f4',count=(N-k)//4,offset=k) for k in range(4)]
hits=collections.Counter(); ex=[]
for m in cp[:60]:
    Lf=np.float32(m['L'])
    for k in range(4):
        F=Fa[k]
        idx=np.nonzero(np.abs(F-Lf)<0.01)[0]
        for j in idx[:200]:
            p=k+4*j
            # outline guess: u array holding L with u0 == 0 somewhere in the 10 slots before
            for s0 in range(1,10):
                st=p-4*s0
                if st<0: continue
                u=np.frombuffer(b[st:st+40],'<f4')
                if abs(u[0])<1e-3 and np.nanmax(u)-np.nanmin(u) > 0 and abs((np.nanmax(u[:s0+1])-min(0,np.nanmin(u[:s0+1])))-m['L'])<0.05:
                    # candidate u array start st; find enclosing record
                    rs=None
                    for S,recs in db.bystride.items():
                        i=np.searchsorted(recs,st,'right')-1
                        if i>=0 and recs[i]<=st<recs[i]+S: rs=(S,st-int(recs[i])); break
                    hits[rs]+=1
                    if len(ex)<5 and rs: ex.append((m['prof'], round(m['L'],1), rs, [round(float(x),1) for x in u]))
                    break
print(hits.most_common(10)); print(ex)
