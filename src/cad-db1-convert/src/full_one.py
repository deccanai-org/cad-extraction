import sys, json, time; sys.path.insert(0,'src')
from db1dec import *
t=time.time(); db=Db(load(sys.argv[1])); db.segment()
cs=db.find_csys(); pts=db.find_points(); print('tables', round(time.time()-t), [ (p['stride'],p['k'],len(p['keys'])) for p in pts][:4], [(c['stride'],c['k'],c['key'],len(c['keys'])) for c in cs][:4], flush=True)
lay=db.find_members(pts,cs); print('members layout', round(time.time()-t), lay and {k:lay[k] for k in lay if k!='tried'}, flush=True)
if lay and lay.get('csys') is not None:
    db.find_attr(lay); M=members(db,pts,cs,lay)
    import db1dec; print('attr', {k:lay.get(k) for k in ('attr','attr_stride','prof_off','rest_ref','rest_off')}, 'members', len(M), 'named', sum(1 for m in M if m['prof']), 'axis', db1dec._axis_agreement(db,pts,lay,M), round(time.time()-t))
