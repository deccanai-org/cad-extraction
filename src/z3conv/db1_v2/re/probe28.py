import sys, numpy as np, collections, re
from cache import *
from guid2 import guid_keys
import ifcbolts
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
print('lay', {k: lay.get(k) for k in ('stride', 'attr_stride', 'poly_field', 'poly_stride', 'poly_field2', 'poly_stride2')}, 'members', len(M))
seqs = {m['seq']: m for m in M}
G, back, top = guid_keys(db); print('guid join', back, top[:3])
B, GR = ifcbolts.bolts(ifc, True)
c = collections.Counter(); ex = []
for g in GR:
    k = G.get(g['guid'])
    if k is None: c['no_guid'] += 1; continue
    ss = tuple(sorted(int(s) for s, (K, O) in db.seqidx.items() if np.searchsorted(K, k, 'right') > np.searchsorted(K, k, 'left')))
    c[('in_members', k in seqs)] += 1; c[ss] += 1
    if len(ex) < 3 and g['bolts']: ex.append((g, k, ss))
print(c.most_common(10))
d = db.b
for g, k, ss in ex[:2]:
    print('\nGUID', g['guid'], 'key', k, 'strides', ss, 'nb', len(g['bolts']), 'd', g['d'], 'L', g['L'], 'pset', {kk: v for kk, v in g['pset'].items() if kk in ('Bolt hole diameter', 'Slotted hole x', 'Slotted hole y', 'Washer count', 'Nut count', 'Bolt standard')})
    for s in ss:
        K, O = db.seqidx[s]; lo = np.searchsorted(K, k, 'left'); o = int(O[lo])
        print('  stride', s, 'ints', [(j, int(x)) for j, x in zip(range(9, min(s, 120) - 3, 4), db.I(o + np.arange(9, min(s, 120) - 3, 4)))])
        print('     dbl', [(j, round(float(x), 3)) for j, x in zip(range(9, s - 7), db.D(o + np.arange(9, s - 7))) if np.isfinite(x) and 0.5 < abs(x) < 1e7 and abs(x * 100 - round(x * 100)) < 1e-6][:12])
        print('     strs', [(mm.start(), mm.group().decode('latin1')) for mm in re.finditer(rb'[\x20-\x7e]{4,}', d[o:o + s])][:8])
