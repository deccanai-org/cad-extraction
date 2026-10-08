import sys, re, json, glob, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
from db1step import section_for
cat=json.load(open('catalog/tekla_profiles.json')); L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
for f in sorted(glob.glob('pairs/data/so_*.db1')):
    e=f.split('_')[1]; db,pts,cs,lay=decode(f,L[e]['layout'],V,True); M=members(db,pts,cs,lay)
    hz=[m for m in M if not m['cut'] and abs(m['x'][2])<0.1 and m['L']>500 and m['prof']]
    kinds=collections.Counter(); vert=collections.Counter()
    for m in hz:
        k=section_for(m['prof'],cat)[0] or section_for(m['prof'],cat)[1]; kinds[k]+=1; vert[k]+=abs(m['y'][2])>0.996
    print(f.split('/')[-1], 'horizontal by kind', {k:(n, round(vert[k]/n,2)) for k,n in kinds.most_common(6)}, 'top names', collections.Counter(m['prof'] for m in hz).most_common(4))
