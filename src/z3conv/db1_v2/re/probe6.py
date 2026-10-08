import sys, collections, numpy as np, re
from cache import *
from guidmap import db1_guids
import ifcbolts
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
seqs = {m['seq']: m for m in M}
G, info = db1_guids(db.b)
B, GR = ifcbolts.bolts(ifc, True)
pairs = [(g, seqs[G[g['guid']]['key']]) for g in GR if g['guid'] in G and G[g['guid']]['key'] in seqs]
bs = np.array(sorted({m['seq'] for g, m in pairs}), np.int64)
for S in (69, 33):
    recs = db.bystride[S]
    F17 = db.I(recs + 17); sel = recs[inkeys(bs, F17)]
    print('stride', S, 'records with bolt@17', len(sel))
    c = collections.Counter()
    for o in sel[:3000]:
        ints = [int(x) for x in db.I(o + np.arange(9, S - 3, 4))]
        # classify each field: member seq? bolt? other
        tags = []
        for k, v in zip(range(9, S - 3, 4), ints):
            t = 'M' if v in seqs and v not in set(bs.tolist()[:0]) else ('B' if v in set() else '')
            tags.append((k, 'bolt' if inkeys(bs, [v])[0] else ('part' if v in seqs else ('0' if v == 0 else 'x'))))
        c[tuple(tags)] += 1
    for k, v in c.most_common(6): print('  ', v, k)
    for o in sel[:5]: print('   ex', [int(x) for x in db.I(o + np.arange(9, S - 3, 4))], [round(float(x), 3) for x in db.D(o + np.arange(9, S - 7, 4))][:4])
