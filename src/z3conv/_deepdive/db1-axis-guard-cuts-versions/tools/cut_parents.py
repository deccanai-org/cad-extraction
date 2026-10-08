"""Old engines: relation parents (type 11) that are not decoded parts: is there a part record for them that failed a reference?"""
import sys, os, re, collections, numpy as np
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(H, '..', 'kit_patched'))
import db1old
from db1dec import load
for f in sys.argv[1:]:
    data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    if eng >= 7.5: continue
    M, info, cut_rel = db1old.read(data, eng)
    P = db1old.PART_NEW if eng >= 7.1 else db1old.PART_OLD
    pids = {m['pid'] for m in M}; byp = {m['pid']: m for m in M}
    miss = [p for p in cut_rel if p not in pids]
    o = db1old.Old(data); I = o.I_all; D = o.D_all; N = len(I) - 400
    print('==', os.path.basename(f)[:12], 'relation parents not decoded:', len(miss))
    res = collections.Counter()
    for p in miss[:40]:
        occ = [int(q) for q in np.nonzero(I[:N] == p)[0]]
        # candidate part record: id at q, attr at q+P['attr'] > 0, finite csys length
        cands = []
        for q in occ:
            if q + P['csys'] + 32 >= len(D): continue
            Ln = D[q + P['csys'] + 24]
            if np.isfinite(Ln) and 0 <= Ln < 1e6 and I[q + P['attr']] > 0:
                cands.append((q, data[q - 1], int(I[q + P['attr']]), int(I[q + P['p1']]), int(I[q + P['p2']]), int(I[q + P['csa']]), round(float(Ln), 1)))
        cutters = cut_rel[p]
        cp = [byp[c]['prof'] for c in cutters if c in byp]
        res['has part-like record' if cands else 'no part record'] += 1
        if len([1 for k in res]) and sum(res.values()) <= 6:
            print('  parent', p, 'cutters', cutters[:4], cp[:4], 'occurrences', len(occ), 'part-like', cands[:3])
    print('  summary', dict(res))
