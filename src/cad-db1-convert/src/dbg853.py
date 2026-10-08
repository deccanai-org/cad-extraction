import sys, json, collections, numpy as np
sys.path.insert(0, '/opt/db1v2/src')
from db1dec import *
L = json.load(open('/opt/db1v2/layouts.json')); lay0 = L['8.53']['layout']
db = Db(load('/opt/db1v2/pairs/8.53_0575f7270f.db1')); db.segment()
pts = db.find_points(fixed=(lay0['pts_stride'], lay0['pts_k'])); print('pts fixed', [(p['stride'], p['k'], len(p['keys'])) for p in pts])
cs = db.find_csys(only=(lay0['csys_stride'], lay0['csys_k'])); print('csys', [(c['stride'], c['k'], c['key'], len(c['keys'])) for c in cs])
recs = db.bystride.get(lay0['stride']); print('member recs', None if recs is None else len(recs))
lay = dict(lay0); lay['pts'] = 0; db._member_run = recs
m = members(db, pts, cs, lay); print('fast members', len(m), 'with prof', sum(1 for x in m if x['prof']))
for f in (33, 37):
    for C in cs: print('  field', f, C['key'], 'frac', round(float(inkeys(C['keys'], db.I(recs + f)).mean()), 3))
P = pts[0] if pts else None
if P is not None:
    for f in (17, 21, 25, 29): print('  pts field', f, round(float(inkeys(P['keys'], db.I(recs + f)).mean()), 3))
