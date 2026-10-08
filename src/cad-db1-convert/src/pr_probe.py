import sys, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
db=Db(load(sys.argv[1])); db.segment()
recs=db.bystride[41]
def ok(k):
    x,y,z,v=db._xyz(recs,k); return v & db._nice(x) & db._nice(y) & db._nice(z)
a,b=ok(17),ok(12)
print('stride41', len(recs), 'k17', int(a.sum()), 'k12', int(b.sum()), 'both', int((a&b).sum()))
for name,m in (('k12only', b&~a), ('k17only', a&~b)):
    for o in recs[m][:3]:
        o=int(o); print(name, o, db.b[o:o+41].hex(' '))
        print('    ints', [int(x) for x in db.I(o+np.arange(0,41,4))], 'flag', db.b[o+8], 'D@12', [round(float(x),2) for x in db.D(o+12+8*np.arange(3))], 'D@17', [round(float(x),2) for x in db.D(o+17+8*np.arange(3))])
