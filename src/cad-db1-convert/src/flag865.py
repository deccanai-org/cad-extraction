import sys, re, json, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); lay=dict(L['8.65']['layout']); lay['pts']=0
db=Db(load(sys.argv[1])); db.segment()
pts=db.find_points(fixed=(lay['pts_stride'],lay['pts_k'])); cs=db.find_csys(only=(lay['csys_stride'],lay['csys_k']))
db._member_run=db.bystride.get(lay['stride'])
M=members(db,pts,cs,lay)
miss=sorted({m['attr'] for m in M if int(db.lookup_stride([m['attr']])[0])==-1})
print('attr keys not in runs', len(miss))
K=np.array(miss[:400],np.int64); K.sort()
hits=collections.defaultdict(list)
for a in range(4):
    n=(db.L-a)//4
    for c0 in range(0,n,16_000_000):
        v=np.frombuffer(db.b,'<i4',count=min(16_000_000,n-c0),offset=a+4*c0)
        i=np.searchsorted(K,v); i[i>=len(K)]=0
        for j in np.nonzero(K[i]==v)[0]:
            p=a+4*(c0+int(j)); hits[int(v[j])].append(p)
flag=collections.Counter(); ex=[]
for k,ps in hits.items():
    for p in ps:
        if p>=9 and db.I([p-9])[0]>0 and db.I([p-5])[0]>0 and 0<db.b[p-1]<32:
            flag[db.b[p-1]]+=1
            if len(ex)<6: ex.append((k,p,db.b[p-1],[(mm.start(), mm.group().decode('latin1')) for mm in re.finditer(rb'[\x20-\x7e]{3,}', db.b[p-9:p-9+331])][:8]))
print('keys found', len(hits), 'header flag bytes before key', flag.most_common(10))
for e in ex: print(e)
