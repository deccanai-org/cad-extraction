import sys, re, json, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
from db1step import section_for
cat=json.load(open('catalog/tekla_profiles.json'))
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
f,e=sys.argv[1],sys.argv[2]
db,pts,cs,lay=decode(f,L[e]['layout'],V,True)
M=members(db,pts,cs,lay); c=collections.Counter()
for m in M:
    if m['cut'] or not m['prof']: continue
    rr=db.attr_records(lay,m['attr']); txt=db.b[rr[0]:rr[0]+lay['attr_stride']].upper() if rr else b''
    if b'COLUMN' not in txt: continue
    k,v,how=section_for(m['prof'],cat); fam=k or v
    c[(fam, abs(m['x'][2])>0.9)]+=1
print(sorted(c.items(), key=lambda kv:-kv[1])[:12])
shown=0
for m in M:
    if m['cut'] or not m['prof']: continue
    rr=db.attr_records(lay,m['attr']); txt=db.b[rr[0]:rr[0]+lay['attr_stride']] if rr else b''
    if b'COLUMN' not in txt.upper() or abs(m['x'][2])>0.9: continue
    print(m['prof'], [round(float(x),2) for x in m['x']], round(m['L']), [(mm.start(), mm.group().decode('latin1')) for mm in re.finditer(rb'[\x20-\x7e]{3,}', txt)][:8])
    shown+=1
    if shown>=5: break
