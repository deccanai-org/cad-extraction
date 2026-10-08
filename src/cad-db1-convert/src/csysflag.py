import sys, json, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
f=sys.argv[1]; db=Db(load(f)); db.segment()
recs=db.bystride[73]
for fld in (29,33,37):
    keys=db.I(recs+fld); u=np.unique(keys[keys>0])
    st=collections.Counter(int(s) for s in db.lookup_stride(u)); print('field',fld,'distinct',len(u),'strides',st.most_common(4))
keys=np.unique(db.I(recs+33)); keys=keys[keys>0][:3000]
fl=db.flagged(list(keys)); hit=[k for k,v in fl.items() if v]
print('flagged hits', len(hit), 'of', len(keys))
flags=collections.Counter(); ex=[]
for k in hit[:400]:
    for o in fl[k][:1]:
        flags[db.b[o+8]]+=1
        v=db.D(o+np.arange(9,9+48+48,8)); 
        if len(ex)<3: ex.append((k, o, db.b[o+8], [round(float(x),3) for x in db.D(o+13+8*np.arange(8))]))
print(flags, ex)
