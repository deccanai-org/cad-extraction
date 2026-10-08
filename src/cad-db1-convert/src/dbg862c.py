import sys, json, re, collections, numpy as np
sys.path.insert(0, '/opt/db1v2/src3')
from db1dec import *
L = json.load(open('/opt/db1v2/layouts.json')); variants = [v['layout'] for v in L.values() if v.get('layout')]
db, pts, cs, lay = decode(sys.argv[1], L['8.62']['layout'], variants, False)
M = members(db, pts, cs, lay)
cp = [m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
found = collections.Counter(); shown = 0
for m in cp[:400]:
    seq = int(db.I([m['off'] + 9])[0])
    for s, (K, O) in db.seqidx.items():
        for o in db.lookup_all(seq, s):
            if s == lay['stride'] and o == m['off']: continue
            f4 = db.F(o + np.arange(0, min(s, 1500), 1))   # every byte offset
            hit = [k for k in range(min(s, 1500) - 4) if abs(f4[k] - m['L']) < 0.05]
            if hit:
                found[(s, tuple(hit[:3]))] += 1
                if shown < 3:
                    shown += 1
                    k0 = hit[0] - 4
                    print('plate', m['prof'], 'L', round(m['L'], 2), 'stride', s, 'hits', hit[:4],
                          'f32 from u0?', [round(float(x), 2) for x in db.F(o + k0 + 4 * np.arange(24))])
print(found.most_common(8))
