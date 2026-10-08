import sys, re, json, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); lay=dict(L['8.65']['layout']); lay['pts']=0
db=Db(load(sys.argv[1])); db.segment()
pts=db.find_points(fixed=(lay['pts_stride'],lay['pts_k'])); cs=db.find_csys(only=(lay['csys_stride'],lay['csys_k']))
db._member_run=db.bystride.get(lay['stride'])
M=members(db,pts,cs,lay)
A=collections.Counter(x['attr'] for x in M)
keys=np.array(list(A)); st=db.lookup_stride(keys)
print('attr key strides', collections.Counter(int(s) for s in st).most_common(6))
k317=[int(k) for k,s in zip(keys,st) if s==317][:6]
for a in k317[:4]:
    o=db.lookup([a],317)[0]
    print('--', a, 'off', o, [(m.start(), m.group().decode('latin1')) for m in re.finditer(rb'[\x20-\x7e]{2,}', db.b[o:o+317])][:14])
# compare with a 331 record, if any
k331=[int(k) for k,s in zip(keys,st) if s==331][:2]
for a in k331:
    o=db.lookup([a],331)[0]
    print('== 331', a, [(m.start(), m.group().decode('latin1')) for m in re.finditer(rb'[\x20-\x7e]{2,}', db.b[o:o+331])][:14])
print('#####')
by=collections.Counter(); ex=[]
for m in M:
    s=int(db.lookup_stride([m['attr']])[0]); by[(s, bool(m['prof']))]+=1
    if s==331 and not m['prof'] and len(ex)<8: ex.append(m)
print('members by attr stride / has prof', by.most_common())
for m in ex:
    o=int(db.lookup([m['attr']],331)[0]); buf=db._buf(o+lay['prof_off']); ref=int(db.I([o+lay['rest_ref']])[0])
    rc=db.lookup_all(ref); 
    print('attr',m['attr'],'buf',repr(buf[:40]),'rest_ref',ref,'->',[(r, int(db.lookup_stride([ref])[0]), repr(db.cstr(r+lay['rest_off'],60))) for r in rc[:3]], 'strings', [(mm.start(), mm.group().decode('latin1')) for mm in re.finditer(rb'[\x20-\x7e]{2,}', db.b[o:o+331])][:10])
