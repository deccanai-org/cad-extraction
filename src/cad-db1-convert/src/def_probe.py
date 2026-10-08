import sys, json, time, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json'))
f, eng = sys.argv[1], sys.argv[2]; base=L[eng]['layout']
t=time.time(); db=Db(load(f)); db.segment(); print(f.split('/')[-1], 'segment', round(time.time()-t,1), 's; runs', len(db.runs))
bys=sorted(((s, len(r)) for s, r in db.bystride.items()), key=lambda x:-x[1])[:15]; print(' biggest strides', bys)
print(' base pts', base['pts_stride'], base['pts_k'], 'member stride', base['stride'], 'csys', base['csys_stride'], base['csys_k'])
t=time.time(); P=db.find_points(fixed=(base['pts_stride'], base['pts_k'])); print(' fixed points ->', [ (p['stride'],p['k'],len(p['keys'])) for p in P][:3] if P else P, round(time.time()-t,1))
t=time.time(); P=db.find_points(); print(' free points ->', [ (p['stride'],p['k'],len(p['keys'])) for p in P][:4] if P else P, round(time.time()-t,1))
t=time.time(); C=db.find_csys(); print(' free csys ->', [ (c['stride'],c['k'],c['key'],len(c['keys'])) for c in C][:4], round(time.time()-t,1))
