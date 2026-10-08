import sys, json, time, collections, numpy as np, re
sys.path.insert(0, 'src')
from db1dec import *
L = json.load(open('src/layouts.json'))
f = sys.argv[1]; eng = sys.argv[2]
data = load(f); db = Db(data); db.segment()
cand = L[eng]['layout']; print(cand)
pts = db.find_points(fixed=(cand['pts_stride'], cand['pts_k'])); print('pts tables', [(p['stride'], p['k'], len(p['keys'])) for p in pts])
cs = db.find_csys(only=(cand['csys_stride'], cand['csys_k'])); print('csys', [(c['stride'], c['k'], c['key'], len(c['keys'])) for c in cs])
lay = dict(cand); lay['pts'] = 0
recs = db.bystride.get(lay['stride']); db._member_run = recs
M = members(db, pts, cs, lay); print('members', len(M), 'with prof', sum(1 for m in M if m['prof']))
print('accept', _accept(db, lay, M), 'axis', _axis_agreement(db, pts, lay, M))
print(collections.Counter(m['prof'] for m in M).most_common(10))
# raw check of member run: how many 73-records have resolvable points/csys
X = np.stack([db.D(recs + 41 + 8 * i) for i in range(4)], 1)
P = pts[0] if pts else None
if P is not None:
    p1 = db._pt(P, db.I(recs + 21)); p2 = db._pt(P, db.I(recs + 25))
    print('73 recs', len(recs), 'p1 ok', np.isfinite(p1).all(1).mean(), 'p2 ok', np.isfinite(p2).all(1).mean())
    for c in cs: print('  csys', c['key'], inkeys(c['keys'], db.I(recs + 33)).mean())
attrs = db.I(recs + 13); print('attr in 341', np.mean([bool(db.lookup_all(int(a), 341)) for a in attrs[:300]]), 'attr in 331', np.mean([bool(db.lookup_all(int(a), 331)) for a in attrs[:300]]))
st = collections.Counter(int(db.lookup_stride([int(a)])[0]) for a in attrs[:500]); print('attr key strides', st.most_common(8))
