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
# all record starts sorted with stride, to map an offset to (stride, field)
allo = []; alls = []
for s, recs in db.bystride.items(): allo.append(recs); alls.append(np.full(len(recs), s))
allo = np.concatenate(allo); alls = np.concatenate(alls); o = np.argsort(allo); allo = allo[o]; alls = alls[o]
cnt = collections.Counter(); ex = {}
for a in range(4):
    v = np.frombuffer(db.b, '<i4', count=(db.L - a) // 4, offset=a)
    hit = np.nonzero(inkeys(bs, v))[0]
    for j in hit:
        p = a + 4 * int(j)
        i = np.searchsorted(allo, p, 'right') - 1
        if i < 0: cnt[('none',)] += 1; continue
        s = int(alls[i]); f = p - int(allo[i])
        if f >= s: cnt[('outside',)] += 1; continue
        cnt[(s, f)] += 1; ex.setdefault((s, f), int(allo[i]))
print('bolt seqs', len(bs))
for k, v in cnt.most_common(25): print(v, k, ex.get(k))
