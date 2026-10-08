import sys, json, time, collections, numpy as np; sys.path.insert(0,'src')
import db1dec
from db1dec import *
L=json.load(open('layouts.json')); base=dict(L[sys.argv[2]]['layout'])
t=time.time(); db=Db(load(sys.argv[1])); db.segment(); print('segment', round(time.time()-t))
pts=db.find_points(fixed=(base['pts_stride'],base['pts_k'])); print('points tables', len(pts), [len(p) for p in pts][:3] if pts else None)
cs=db.find_csys(only=(base.get('csys_stride') or 61, base.get('csys_k') or 9)); print('csys tables', len(cs), [(c['stride'],c['k'],c['key'],len(c['keys'])) for c in cs][:4])
recs=db.bystride.get(base['stride']); print('member recs', None if recs is None else len(recs))
t=time.time(); p2, c2, lay = db1dec._semi(db, base); print('semi', round(time.time()-t), 's ->', None if not lay else {k:lay.get(k) for k in ('csys','csys_key','csys_frac','attr','attr_stride','prof_off','rest_ref','rest_stride','rest_off','prof_score')})
if lay:
    M=members(db,p2,c2,lay); withp=sum(1 for x in M if x['prof'])
    print('members', len(M), 'withp', withp, round(withp/max(1,len(M)),3), 'accept', db1dec._accept(db, lay, M), 'webvert', db1dec._web_vertical(M))
    print(collections.Counter(x['prof'] for x in M).most_common(15))
