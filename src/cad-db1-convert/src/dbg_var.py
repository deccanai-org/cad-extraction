import sys, json, collections, re, time, numpy as np
sys.path.insert(0, '/opt/db1v2/src')
from db1dec import *
f = sys.argv[1]; t = time.time()
db = Db(load(f)); db.segment(); print('seg', round(time.time() - t, 1), 'L', db.L)
lay = {'stride': 73, 'xyz': 41, 'pts_stride': 41, 'pts_k': 17, 'p1': 21, 'p2': 25, 'csys': 37, 'csys_key': 'after', 'csys_stride': 61, 'csys_k': 9}
pts = db.find_points(fixed=(41, 17)); cs = db.find_csys(only=(61, 9)); lay['pts'] = 0
recs = db.bystride[73]; db._member_run = recs
M = members(db, pts, cs, lay); print('members', len(M))
offs = np.array([m['off'] for m in M])
for fa in range(9, 70, 4):
    if fa in (21, 25, 37) or 38 <= fa < 73: continue
    vals = np.unique(db.I(offs + fa))
    st = db._strides_holding(vals, 0.5)[:4]
    print('field', fa, 'nvals', len(vals), 'strides', st)
    for S in st:
        o = int(db.lookup(vals[:1], S)[0])
        if o >= 0 and S > 100:
            print('   S', S, [(m_.start(), m_.group().decode('latin1')) for m_ in re.finditer(rb'[\x20-\x7e]{2,}', db.b[o:o + S])][:10])
