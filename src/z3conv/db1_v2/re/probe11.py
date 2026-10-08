import sys, numpy as np, collections, pickle
from bolt853 import *
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M, seqs, pairs = setup(db1, ifc)
G, _ = db1_guids(db.b); key2g = {v['key']: k for k, v in G.items()}
T = pickle.load(open(ifc + '.tagtruth.pkl', 'rb'))
r69 = db.bystride[69]; ty = db.I(r69 + 13); b = db.I(r69 + 17); p = db.I(r69 + 21)
rel = collections.defaultdict(list)
for t_, bb, pp in zip(ty, b, p):
    if t_ == 10: rel[int(bb)].append(int(pp))
def beam_shift(seq):
    """translation between the DB1 member axis and the Tekla IFC extrusion axis (beams/columns only), None if n/a"""
    m = seqs.get(seq); g = key2g.get(seq)
    if m is None or g is None or g not in T: return None
    best = None
    for t in T[g]:
        if t['cls'] not in ('IfcBeam', 'IfcColumn', 'IfcMember'): continue
        if abs(t['L'] - m['L']) > 1: continue
        for a, bb in ((t['a'], t['b']), (t['b'], t['a'])):
            s1 = a - m['O']; s2 = bb - m['E']
            if np.linalg.norm(s1 - s2) < 1 and (best is None or np.linalg.norm(s1) < np.linalg.norm(best)): best = (s1 + s2) / 2
    return best
cnt = collections.Counter(); ex = []
for g, m in pairs:
    P = positions(db, m); Tl = truth_local(g, m); c, d = classify(P, Tl)
    sh = [beam_shift(s) for s in rel.get(m['seq'], [])]; sh = [x for x in sh if x is not None]
    if not sh: cnt[(c, 'no_beam')] += 1; continue
    same = all(np.linalg.norm(x) < 0.5 for x in sh)
    cnt[(c, 'beams_unchanged' if same else 'beam_moved')] += 1
    if c in ('translated', 'other', 'count') and len(ex) < 12: ex.append((c, g['guid'][:8], None if d is None else np.round(d, 1), [np.round(x, 1).tolist() for x in sh]))
for k, v in sorted(cnt.items()): print(k, v)
for e in ex: print(e)
