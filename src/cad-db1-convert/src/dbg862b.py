import sys, json, re, collections, numpy as np
sys.path.insert(0, '/opt/db1v2/src3')
from db1dec import *
L = json.load(open('/opt/db1v2/layouts.json')); variants = [v['layout'] for v in L.values() if v.get('layout')]
db, pts, cs, lay = decode(sys.argv[1], L['8.62']['layout'], variants, False)
M = members(db, pts, cs, lay)
cp = [m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
for m in cp[:3]:
    ref = int(db.I([m['off'] + 37])[0])
    hits = db.lookup_all(ref)
    print('plate', m['prof'], 'L', round(m['L'], 3), 'ref37', ref, 'records', [(o, [s for s, (K, O) in db.seqidx.items() if o in set(O.tolist())][:1]) for o in hits[:2]])
    for o in hits[:1]:
        f4 = db.F(o + 13 + 4 * np.arange(120)); f8 = db.D(o + 13 + 8 * np.arange(60))
        print('   f32', [round(float(x), 2) if np.isfinite(x) and abs(x) < 1e6 else 'X' for x in f4[:80]])
        print('   f64', [round(float(x), 2) if np.isfinite(x) and abs(x) < 1e7 else 'X' for x in f8[:40]])
        # search for L as float32/float64 anywhere in the record
        for k in range(13, 1400):
            if abs(db.F([o + k])[0] - m['L']) < 0.05: print('   L as f32 at +', k)
            if abs(db.D([o + k])[0] - m['L']) < 0.01: print('   L as f64 at +', k)
