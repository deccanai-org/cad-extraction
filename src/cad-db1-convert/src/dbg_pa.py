import sys, re, collections, numpy as np
sys.path.insert(0, '/opt/db1v2/src3')
from db1dec import *
db = Db(load(sys.argv[1])); db.segment()
recs = db.bystride[73]
vals = np.unique(db.I(recs + 13)); pa = db.lookup(vals, 331); pa = pa[pa >= 0]
print('part_attr records', len(pa))
for o in pa[:5]:
    o = int(o)
    print([(m.start(), m.group().decode('latin1')) for m in re.finditer(rb'[\x20-\x7e]{2,}', db.b[o:o + 331])][:12])
    buf = db._buf(o + 85); ref = int(db.I([o + 149])[0])
    hits = [(S, int(db.lookup([ref], S)[0])) for S in db.seqidx if int(db.lookup([ref], S)[0]) >= 0]
    print('   buf85', repr(buf[:30]), 'ref149', ref, 'resolves in', hits[:5], [repr(db.cstr(r + 25, 40)) for S, r in hits[:3]])
