import sys, numpy as np, collections
from bolt853 import *
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M, seqs, pairs = setup(db1, ifc)
rows = []
for g, m in pairs:
    rr = db.attr_records(lay, m['attr'])
    if not rr: continue
    a = rr[0]; ps = g['pset']; nb = len(g['bolts'])
    I = [int(x) for x in db.I(a + np.arange(9, 317 - 3, 4))]
    B = db.b[a:a + 317]
    rows.append((g, m, a, I, B, ps))
# which bytes vary and correlate with washer/nut per bolt and slots
def key(ps, nb):
    return (round((ps.get('Washer count') or 0) / max(nb, 1), 2), round((ps.get('Nut count') or 0) / max(nb, 1), 2), (ps.get('Slotted hole x') or 0) > 0, (ps.get('Slotted hole y') or 0) > 0, ps.get('Location'))
for off in list(range(13, 60)) + list(range(255, 317)):
    vals = collections.defaultdict(collections.Counter)
    for g, m, a, I, B, ps in rows: vals[key(ps, len(g['bolts']))][B[off]] += 1
    nvals = len(set(v for c in vals.values() for v in c))
    if nvals > 1 and nvals < 20:
        print(off, {k: dict(c.most_common(4)) for k, c in sorted(vals.items(), key=lambda x: -sum(x[1].values()))[:6]})
