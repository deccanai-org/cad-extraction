import sys, json, time, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); lay=dict(L['8.65']['layout']); lay['pts']=0
t=time.time(); db=Db(load(sys.argv[1])); db.segment(); print('segment',round(time.time()-t))
pts=db.find_points(fixed=(lay['pts_stride'],lay['pts_k'])); cs=db.find_csys(only=(lay['csys_stride'],lay['csys_k']))
db._member_run=db.bystride.get(lay['stride'])
M=members(db,pts,cs,lay); print('members',len(M), round(time.time()-t))
withp=sum(1 for x in M if x['prof']); print('withp',withp, round(withp/len(M),3))
inattr=[x for x in M if x.get('attr') is not None and db.lookup_all(x['attr'], lay['attr_stride'])]
print('inattr',len(inattr),'with prof',sum(1 for x in inattr if x['prof']))
print('top profs',collections.Counter(x['prof'] for x in M).most_common(25))
print('webvert',_web_vertical(M))
# which inattr members lack prof: show attr strings of a few
miss=[x for x in inattr if not x['prof']][:8]
for x in miss: print(' miss', x['attr'], list(db.attr_strings(lay, x['attr']).items())[:8])
