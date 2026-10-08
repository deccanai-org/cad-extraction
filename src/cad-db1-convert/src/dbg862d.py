import sys, json, re, collections, numpy as np
sys.path.insert(0, '/opt/db1v2/src3')
from db1dec import *
L = json.load(open('/opt/db1v2/layouts.json')); variants = [v['layout'] for v in L.values() if v.get('layout')]
db, pts, cs, lay = decode(sys.argv[1], L['8.62']['layout'], variants, False)
M = members(db, pts, cs, lay)
cp = [m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
beams = [m for m in M if m['prof'] and not PLATE1_RE.match(m['prof']) and not m['cut']]
print('ints +9..+37 plate:', [[int(db.I([m['off'] + f])[0]) for f in range(9, 41, 4)] for m in cp[:4]])
print('ints +9..+37 beam :', [[int(db.I([m['off'] + f])[0]) for f in range(9, 41, 4)] for m in beams[:3]])
for m in cp[:2]:
    for f in (17, 29, 37):
        v = int(db.I([m['off'] + f])[0])
        for s, (K, O) in db.seqidx.items():
            for o in db.lookup_all(v, s)[:1]:
                raw = db.b[o:o + min(s, 96)]
                print(f'  plate L={m["L"]:.2f} field+{f}={v} -> stride {s}: ints', [int(x) for x in db.I(o + np.arange(0, min(s, 96) - 3, 4))][:20])
                print('        f32', [round(float(x), 2) if abs(x) < 1e6 else 'X' for x in db.F(o + np.arange(0, min(s, 96) - 3, 4))][:20])
