import sys, json, collections, re, time, numpy as np
sys.path.insert(0, '/opt/db1v2/src')
from db1dec import *
f = sys.argv[1]; t = time.time()
db = Db(load(f)); db.segment(); print('seg', round(time.time() - t, 1))
t = time.time(); pts = db.find_points(); print('pts', round(time.time() - t, 1), [(p['stride'], p['k'], len(p['keys'])) for p in pts[:6]])
t = time.time(); cs = db.find_csys(); print('cs', round(time.time() - t, 1), [(c['stride'], c['k'], c['key'], len(c['keys'])) for c in cs][:8])
t = time.time(); lay = db.find_members(pts, cs); print('mem', round(time.time() - t, 1), lay)
M = members(db, pts, cs, lay); print('members', len(M))
offs = np.array([m['off'] for m in M])
for fa in range(9, lay['stride'] - 3, 4):
    if fa in (lay['p1'], lay['p2'], lay['csys']) or lay['xyz'] - 3 < fa < lay['xyz'] + 32: continue
    vals = np.unique(db.I(offs + fa)); st = db._strides_holding(vals, 0.5)[:4]
    print('field', fa, 'nvals', len(vals), 'strides', st)
    for S in st:
        o = int(db.lookup(vals[:1], S)[0])
        if o >= 0 and S > 100:
            print('   S', S, [(m_.start(), m_.group().decode('latin1')) for m_ in re.finditer(rb'[\x20-\x7e]{2,}', db.b[o:o + S])][:10])
