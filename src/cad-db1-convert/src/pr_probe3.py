import sys, json, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); lay=dict(L['8.07']['layout']); lay['pts']=0
db=Db(load(sys.argv[1])); db.segment()
pts=db.find_points(fixed=(lay['pts_stride'],lay['pts_k'])); cs=db.find_csys(only=(61,9))
P=pts[0]; recs=db.bystride[73]
X=np.stack([db.D(recs+41+8*i) for i in range(4)],1); p1=db._pt(P,db.I(recs+21)); p2=db._pt(P,db.I(recs+25))
okL=np.all(np.isfinite(p1),1)&np.all(np.isfinite(p2),1)&(np.abs(np.linalg.norm(p2-p1,axis=1)-X[:,3])<1.0)&(X[:,3]>0)
print('length-valid part records', int(okL.sum()), 'of', len(recs))
for f in (29,33,37):
    v=db.I(recs[okL]+f)
    res={c['key']: float(inkeys(c['keys'],v).mean()) for c in cs}
    st=collections.Counter(int(x) for x in db.lookup_stride(v)); fl=db.flagged(list(np.unique(v[v>0]))[:2000]); nf=sum(1 for k in v if fl.get(int(k)))
    print('field',f,'in csys maps',{k:round(x,3) for k,x in res.items()},'strides',st.most_common(4),'flagged-found',nf)
import db1dec
for f,key in ((33,'after'),(37,'seq'),(29,'seq')):
    C=[c for c in cs if c['key']==key][0]
    trial=dict(lay); trial.update(csys=f, csys_key=key)
    M=members(db,pts,cs,trial)
    print('csys',f,key,'members',len(M),'axis',db1dec._axis_agreement(db,pts,trial,M),'webvert',db1dec._web_vertical(M), 'named', sum(1 for m in M if m['prof']))
