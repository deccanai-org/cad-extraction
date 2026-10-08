import sys, re, collections, numpy as np
sys.path.insert(0, '/opt/db1v2/src')
from db1dec import *
db = Db(load(sys.argv[1])); db.segment()
S = 389; recs = db.bystride[S]; seen = collections.Counter()
for o in recs:
    o = int(o); buf = db._buf(o + 133); ref = int(db.I([o + 197])[0]); rs = int(db.lookup([ref])[0])
    tail = db.cstr(rs + 25, 160) if rs >= 0 else None
    r = db.rebuild(buf, tail or '')
    if r is None:
        key = (buf[:30], tail)
        if seen[key] == 0:
            print(repr(buf[:40]), '| tail', repr(tail), '| ref', ref, rs, '| strings', [(m.start(), m.group().decode('latin1')) for m in re.finditer(rb'[\x20-\x7e]{2,}', db.b[o:o+S])][:6])
        seen[key] += 1
    if len(seen) > 14: break
