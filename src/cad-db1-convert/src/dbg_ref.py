import sys, collections, re, numpy as np
sys.path.insert(0, '/opt/db1v2/src')
from db1dec import *
db = Db(load(sys.argv[1])); db.segment()
S = 389; recs = db.bystride[S]
# objid index
ob = db.I(np.concatenate([r for s, r in db.runs])); allrecs = np.concatenate([r for s, r in db.runs])
o_sorted = np.argsort(ob); obk = ob[o_sorted]; obo = allrecs[o_sorted]
def by_obj(v):
    i = np.searchsorted(obk, v); i2 = np.minimum(i, len(obk) - 1); return np.where(obk[i2] == v, obo[i2], -1)
for o in recs[:6]:
    o = int(o); buf = db._buf(o + 133); ref = int(db.I([o + 197])[0])
    rs = int(db.lookup([ref])[0]); ro = int(by_obj(np.array([ref]))[0])
    print(repr(buf[:40]), 'ref', ref, 'by_seq', rs, repr(db.cstr(rs + 25, 60)) if rs >= 0 else '-', 'by_obj', ro, [(m.start(), m.group().decode('latin1')) for m in re.finditer(rb'[\x20-\x7e]{2,}', db.b[ro:ro + 80])] if ro >= 0 else '-')
