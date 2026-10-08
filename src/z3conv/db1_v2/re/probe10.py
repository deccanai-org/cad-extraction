import sys, numpy as np, collections, pickle, os
from bolt853 import *
import ifctruth, ifcopenshell
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M, seqs, pairs = setup(db1, ifc)
G, _ = db1_guids(db.b)
key2g = {v['key']: k for k, v in G.items()}
tp = ifc + '.tagtruth.pkl'
if not os.path.exists(tp):
    f = ifcopenshell.open(ifc); tr = ifctruth.truth(ifc)
    g2tag = {e.GlobalId: (getattr(e, 'Tag', None) or '')[2:38].upper() for e in f.by_type('IfcElement')}
    T = {}
    for t in tr: T.setdefault(g2tag.get(t['guid']), []).append(t)
    pickle.dump(T, open(tp, 'wb'))
T = pickle.load(open(tp, 'rb'))
# relations bolt -> parts (stride 69, type 10)
r69 = db.bystride[69]; ty = db.I(r69 + 13); b = db.I(r69 + 17); p = db.I(r69 + 21)
rel = collections.defaultdict(list)
for t_, bb, pp in zip(ty, b, p):
    if t_ == 10: rel[int(bb)].append(int(pp))
def part_dev(seq):
    m = seqs.get(seq); g = key2g.get(seq)
    if m is None or g is None or g not in T: return None
    best = None
    for t in T[g]:
        for a, bb in ((t['a'], t['b']), (t['b'], t['a'])):
            d = max(np.linalg.norm(a - m['O']), np.linalg.norm(bb - m['E']))
            if best is None or d < best: best = d
    return best
cnt = collections.Counter(); ex = []
for g, m in pairs:
    P = positions(db, m); Tl = truth_local(g, m); c, d = classify(P, Tl)
    devs = [part_dev(s) for s in rel.get(m['seq'], [])]
    devs = [x for x in devs if x is not None]
    if not devs: cnt[(c, 'no_parts')] += 1; continue
    mx = max(devs)
    cnt[(c, 'parts_same' if mx < 1 else ('parts_moved' if mx < 1e9 else '?'))] += 1
    if c == 'translated' and len(ex) < 10: ex.append((g['guid'][:8], np.round(d, 1), [round(x, 1) for x in devs]))
for k, v in sorted(cnt.items()): print(k, v)
for e in ex: print(e)
