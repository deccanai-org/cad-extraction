import sys, json, re, pickle, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
tag='8.53_0575f7270f'
PL=[p for p in pickle.load(open(f'pairs/data/{tag}.ifc.plates.pkl','rb')) if p['cls']=='IfcPlate']
db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L['8.53']['layout'],V,False)
M=members(db,pts,cs,lay)
cp=[m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
Os=np.array([m['O'] for m in cp])
b=db.b; found=collections.Counter(); ex=[]
for p in PL:
    mid=p['pts'][:-1]+p['n']*p['t']/2
    for vtx in mid:
        dd=np.linalg.norm(Os-vtx,axis=1); j=int(np.argmin(dd))
        if dd[j]>1: continue
        m=cp[j]; uv=[((q-m['O'])@m['x'],(q-m['O'])@m['y']) for q in mid]
        # order vertices starting from the one at O
        k0=int(np.argmin([abs(a)+abs(c) for a,c in uv])); uv=uv[k0:]+uv[:k0]
        us=[round(a,1) for a,c in uv]; vs=[round(c,1) for a,c in uv]
        if len(uv)<4 or len(set(us))<2: continue
        # search float32 sequence of the 2nd and 3rd u values (either vertex order)
        for seq_u in ([uv[1][0],uv[2][0]], [uv[-1][0],uv[-2][0]]):
            pat=b''.join(np.float32(x).tobytes() for x in seq_u)
            hits=[mm.start() for mm in re.finditer(re.escape(pat),b)][:3]
            if hits:
                found['hit']+=1
                if len(ex)<4: ex.append((m['prof'],round(m['L'],1),[round(a,1) for a,c in uv],[round(c,1) for a,c in uv],hits, m['off'], [int(db.I([m['off']+f])[0]) for f in range(9,41,4)]))
                break
        else: found['nohit']+=1
        break
print(found)
for e in ex: print(e)
