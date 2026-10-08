import sys, json, time, collections, numpy as np, re
sys.path.insert(0, 'src')
import db1dec; from db1dec import *
L = json.load(open('src/layouts.json'))
f = sys.argv[1]; eng = sys.argv[2]
data = load(f); t = time.time(); db = Db(data); db.segment(); print('len', len(data), 'segment', round(time.time() - t, 1))
c = collections.Counter({s: len(r) for s, r in db.bystride.items()}); print('top strides', c.most_common(25))
cand = L[eng]['layout']
pts = db.find_points(fixed=(cand['pts_stride'], cand['pts_k'])); print('pts', [(p['stride'], p['k'], len(p['keys'])) for p in pts])
cs = db.find_csys(only=(cand['csys_stride'], cand['csys_k'])); print('csys', [(c['stride'], c['k'], c['key'], len(c['keys'])) for c in cs])
lay = dict(cand); lay['pts'] = 0
recs = db.bystride.get(lay['stride']); db._member_run = recs
print('member stride recs', None if recs is None else len(recs))
if pts and cs:
    M = members(db, pts, cs, lay); print('members', len(M), 'prof', sum(1 for m in M if m['prof']), 'accept', db1dec._accept(db, lay, M), 'axis', db1dec._axis_agreement(db, pts, lay, M))
    print(collections.Counter(m['prof'] for m in M).most_common(8))
    print('attr strides', collections.Counter(int(db.lookup_stride([m['attr']])[0]) for m in M[:2000]).most_common(5))
