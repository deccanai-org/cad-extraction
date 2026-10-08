import sys, collections, numpy as np, json, time
sys.path.insert(0, '/opt/db1v2/src')
from db1dec import *
f = sys.argv[1]; t = time.time()
db = Db(load(f)); db.segment(); print('L', db.L, 'seg', round(time.time() - t, 1), 'runs', len(db.runs))
print('stride73 runs', [len(r) for s, r in db.runs if s == 73][:30], 'bystride73', len(db.bystride.get(73, [])))
print('big strides', sorted(((len(r), s) for s, r in db.bystride.items()), reverse=True)[:15])
lay = json.load(open('/opt/db1v2/src/l807.json'))
pts = db.find_points(fixed=(41, 17)); print('pts fixed', [(p['stride'], p['k'], len(p['keys'])) for p in pts])
cs = db.find_csys(); print('csys', {k: len(v[1]) for k, v in cs.items()})
recs = db.bystride.get(73, np.zeros(0, np.int64))
P = pts[0] if pts else None
if P is not None and len(recs):
    for f_ in (21, 25): print('field', f_, 'in point keys', round(inkeys(P['keys'], db.I(recs + f_)).mean(), 3))
    print('csys33 in after', round(inkeys(cs['after'][1], db.I(recs + 33)).mean(), 3), 'csys37', round(inkeys(cs['after'][1], db.I(recs + 37)).mean(), 3))
    L = db.D(recs + 65); print('len>0 frac', round(((L > 0) & np.isfinite(L)).mean(), 3))
