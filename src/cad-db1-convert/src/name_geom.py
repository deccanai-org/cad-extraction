"""attr-link sanity: COLUMN-named parts should mostly stand vertical, BEAM-named mostly lie flat."""
import sys, re, json, glob, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
near={'9.08':'8.95','7.98':'8.07','8.44':'8.53','8.37':'8.07','7.62':'7.64'}
for f in sys.argv[1:]:
    tag=f.split('/')[-1]; eng=re.search(r'_(\d\.\d\d)_', f).group(1) if re.search(r'_(\d\.\d\d)_', f) else f.split('/')[-1][:4]
    base=(L.get(eng) or {}).get('layout') or L[near.get(eng, eng)]['layout']
    db,pts,cs,lay=decode(f, base, V, False)
    M=members(db,pts,cs,lay)
    c=collections.Counter()
    for m in M:
        if m['attr'] is None or not m['prof']: continue
        recs=db.attr_records(lay, m['attr'])
        if not recs: continue
        txt=db.b[recs[0]:recs[0]+lay['attr_stride']].upper()
        vert=abs(m['x'][2])>0.9; flat=abs(m['x'][2])<0.1
        if b'COLUMN' in txt: c['col']+=1; c['col_vert']+=vert
        elif b'BEAM' in txt and b'PLATE' not in txt: c['beam']+=1; c['beam_flat']+=flat
    fr=lambda a,b: round(c[a]/c[b],3) if c[b] else None
    print(tag, 'COLUMN parts', c['col'], 'vertical', fr('col_vert','col'), '| BEAM parts', c['beam'], 'horizontal', fr('beam_flat','beam'))
