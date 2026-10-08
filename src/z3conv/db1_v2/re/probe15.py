import sys, numpy as np, collections
from bolt853 import *
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M, seqs, pairs = setup(db1, ifc)
rows = []
for g, m in pairs:
    rr = db.attr_records(lay, m['attr'])
    if not rr: continue
    a = rr[0]; ps = g['pset']; nb = max(1, len(g['bolts']))
    rows.append((round((ps.get('Washer count') or 0) / nb, 2), round((ps.get('Nut count') or 0) / nb, 2), a, g))
tgt = collections.Counter((w, n) for w, n, a, g in rows); print('targets', tgt)
best = []
for k in range(9, 317 - 3):
    for kind in ('B', 'I'):
        vals = [(w, n, int(db.u8[a + k]) if kind == 'B' else int(db.I([a + k])[0])) for w, n, a, g in rows]
        # purity: for each value, majority target share
        byv = collections.defaultdict(collections.Counter)
        for w, n, v in vals: byv[v][(w, n)] += 1
        if len(byv) < 2 or len(byv) > 40: continue
        pur = sum(c.most_common(1)[0][1] for c in byv.values()) / len(vals)
        best.append((pur, k, kind, {v: dict(c.most_common(3)) for v, c in sorted(byv.items(), key=lambda x: -sum(x[1].values()))[:6]}))
best.sort(key=lambda x: -x[0])
for b in best[:12]: print(round(b[0], 3), b[1], b[2], b[3])
