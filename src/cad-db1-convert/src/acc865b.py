import sys, json, time, collections, pickle, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); lay=dict(L['8.65']['layout']); lay['pts']=0
print({k:lay.get(k) for k in ('stride','attr','attr_stride','prof_off','rest_ref','rest_stride','rest_off')})
db=Db(load(sys.argv[1])); db.segment()
pts=db.find_points(fixed=(lay['pts_stride'],lay['pts_k'])); cs=db.find_csys(only=(lay['csys_stride'],lay['csys_k']))
db._member_run=db.bystride.get(lay['stride'])
M=members(db,pts,cs,lay)
A=collections.Counter(x['attr'] for x in M)
print('distinct attr keys',len(A))
st=collections.Counter(int(db.lookup_stride([a])[0]) for a in list(A)[:3000]); print('attr key strides',st.most_common(8))
for a,_ in A.most_common(6):
    for o in db.lookup_all(a)[:1]:
        s=int(db.lookup_stride([a])[0]); print('--attr',a,'stride',s,'off',o)
        import re
        print([ (m.start(), m.group().decode('latin1')) for m in re.finditer(rb'[\x20-\x7e]{2,}', db.b[o:o+s])][:12])
pickle.dump(dict(lay=lay),open('/tmp/x.pkl','wb'))
