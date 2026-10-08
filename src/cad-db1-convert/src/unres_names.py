import sys, re, json, collections; sys.path.insert(0,'src')
from db1dec import *
from db1step import section_for
cat=json.load(open('catalog/tekla_profiles.json'))
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
near={'9.08':'8.95','7.98':'8.07','8.44':'8.53','8.37':'8.07'}
f=sys.argv[1]; eng=re.search(r'_(\d\.\d\d)_', f).group(1)
db,pts,cs,lay=decode(f, (L.get(eng) or {}).get('layout') or L[near[eng]]['layout'], V, False)
M=members(db,pts,cs,lay)
c=collections.Counter(); nop=collections.Counter()
for m in M:
    if m['cut']: continue
    if not m['prof']:
        recs=db.attr_records(lay, m['attr']) if m['attr'] is not None else []
        nop[repr([s for s in re.findall(rb'[\x20-\x7e]{3,}', db.b[recs[0]:recs[0]+lay['attr_stride']])][:4]) if recs else 'no attr rec']+=1
        continue
    k,v,how=section_for(m['prof'],cat)
    if k is None and v=='unresolved': c[m['prof']]+=1
print('unresolved', c.most_common(15)); print('no profile (attr strings)', nop.most_common(6))
print('layout', {k:lay.get(k) for k in ('attr','attr_stride','prof_off','rest_ref','rest_stride','rest_off')})
