import sys, re, json, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); lay=dict(L['8.65']['layout']); lay['pts']=0
db=Db(load(sys.argv[1])); db.segment()
pts=db.find_points(fixed=(lay['pts_stride'],lay['pts_k'])); cs=db.find_csys(only=(lay['csys_stride'],lay['csys_k']))
db._member_run=db.bystride.get(lay['stride'])
M=members(db,pts,cs,lay)
by=collections.defaultdict(list)
for m in M:
    if m['prof']: continue
    by[int(db.lookup_stride([m['attr']])[0])].append(m)
for st, ms in sorted(by.items(), key=lambda kv:-len(kv[1])):
    Ls=np.array([m['L'] for m in ms])
    ex=ms[0]; recs=db.attr_records(lay, ex['attr']) if st!=-1 else db.flagged([ex['attr']])[ex['attr']]
    strs=[(mm.start(), mm.group().decode('latin1')) for mm in re.finditer(rb'[\x20-\x7e]{3,}', db.b[recs[0]:recs[0]+max(st,300)])][:8] if recs else None
    print('attr stride', st, 'members', len(ms), 'L median', round(float(np.median(Ls)),1), 'record strings', strs)
