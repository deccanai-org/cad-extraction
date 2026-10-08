import sys, json, time, collections, numpy as np, re
sys.path.insert(0, 'src')
from db1dec import *
L = json.load(open('src/layouts.json')); VA = [v['layout'] for v in L.values() if v.get('layout')]
f = sys.argv[1]; eng = sys.argv[2]
data = load(f)
t = time.time(); db, pts, cs, lay = decode(data, L[eng]['layout'], VA, True); print('decode', round(time.time() - t, 1))
print('lay', {k: v for k, v in (lay or {}).items() if k != 'tried'}); print('tried', (lay or {}).get('tried'))
if lay and lay.get('csys') is not None:
    M = members(db, pts, cs, lay); print('members', len(M), collections.Counter(m['prof'] for m in M).most_common(15))
for s in (125, 149, 49):
    recs = db.bystride.get(s)
    if recs is None: continue
    for o in recs[:3]:
        print(s, [(mm.start(), mm.group().decode('latin1')) for mm in re.finditer(rb'[\x20-\x7e]{3,}', db.b[o:o + s])][:8])
