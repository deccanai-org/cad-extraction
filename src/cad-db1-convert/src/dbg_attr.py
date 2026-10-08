import sys, collections, numpy as np
sys.path.insert(0, '/opt/db1v2/src')
from db1dec import *
f = sys.argv[1]
db = Db(load(f)); db.segment(); pts = db.find_points(); cs = db.find_csys(); lay = db.find_members(pts, cs)
print('LAY', lay)
recs = db._member_run
for fa in range(9, lay['stride'] - 3):
    vals = db.I(recs + fa); st = db.lookup_stride(vals)
    frac = (st > 0).mean()
    if frac < 0.5: continue
    S = collections.Counter(st[st > 0].tolist()).most_common(1)[0][0]
    print('field', fa, 'resolves', round(frac, 2), 'to stride', S, round((st == S).mean(), 2))
S = int(sys.argv[2]) if len(sys.argv) > 2 else 389
fa = int(sys.argv[3]) if len(sys.argv) > 3 else 13
vals = db.I(recs + fa); pa = np.unique(db.lookup(vals, S)); pa = pa[pa >= 0]; print('pa records', len(pa))
import re
for o in pa[:3]:
    print([(m.start(), m.group().decode('latin1')) for m in re.finditer(rb'[\x20-\x7e]{2,}', db.b[int(o):int(o) + S])])
    raw = db.b[int(o):int(o) + S]
    print('   hex@125..160', raw[125:160])
