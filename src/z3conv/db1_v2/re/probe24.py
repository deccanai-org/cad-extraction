import sys, numpy as np, collections, re
from cache import *
from guid2 import guid_keys
import ifcbolts
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
seqs = {m['seq']: m for m in M}
G, back, top = guid_keys(db, np.array(sorted(seqs), np.int64)); print('back', back, top)
B, GR = ifcbolts.bolts(ifc, True)
c = collections.Counter(); ex = []
for g in GR:
    k = G.get(g['guid'])
    if k is None: c['no_guid'] += 1; continue
    ss = tuple(sorted(int(s) for s, (K, O) in db.seqidx.items() if np.searchsorted(K, k, 'right') > np.searchsorted(K, k, 'left')))
    c[('in_members', k in seqs)] += 1; c[ss] += 1
    if len(ex) < 3: ex.append((g['guid'], k, ss, len(g['bolts']), g['d'], g['L']))
print(c.most_common(12)); print(ex)
# GUID strings near the fastener GUID: dump record around
d = db.b
for gg, k, ss, nb, dd, LL in ex[:2]:
    p = d.find(gg.encode()); p = p if p >= 0 else d.find(gg.lower().encode())
    print(gg, 'at', p, d[p - 60:p + 40])
    for s in ss:
        K, O = db.seqidx[s]; lo = np.searchsorted(K, k, 'left')
        o = int(O[lo]); raw = d[o:o + s]
        print('  stride', s, 'ints', [int(x) for x in db.I(o + np.arange(9, min(s, 140) - 3, 4))])
        print('     floats', [(j, round(float(x), 3)) for j, x in zip(range(9, s - 3), db.F(o + np.arange(9, s - 3))) if np.isfinite(x) and 0.5 < abs(x) < 1e6 and abs(x * 100 - round(x * 100)) < 1e-3][:40])
        print('     strs', [(mm.start(), mm.group().decode('latin1')) for mm in re.finditer(rb'[\x20-\x7e]{3,}', raw)][:12])
