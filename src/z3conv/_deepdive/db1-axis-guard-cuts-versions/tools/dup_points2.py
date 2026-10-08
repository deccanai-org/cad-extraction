"""Characterise every conflicting duplicate point id: prefix byte, vis, coordinate sanity of each copy, and which copy db1old keeps (last)."""
import sys, os, re, collections, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'kit_snapshot'))
import db1old
from db1dec import load
def denorm(x): return x != 0 and abs(x) < 1e-100
for f in sys.argv[1:]:
    data = load(f)
    o = db1old.Old(data); I = o.I_all; D = o.D_all
    N = len(I) - 400
    pv = np.zeros(N, bool)
    pv[:N - 32] = (I[:N - 32] > 0) & (I[4:N - 28] >= 0) & (I[4:N - 28] <= 64)
    for k in (8, 16, 24):
        v = D[k:N - 32 + k]; pv[:N - 32] &= np.isfinite(v) & (np.abs(v) < 1e8)
    pts_off = o.runs(pv, 33)
    pre = collections.Counter(data[int(q) - 1] for q in pts_off)
    byid = collections.defaultdict(list)
    for q in pts_off: byid[int(I[q])].append(int(q))
    conf = {k: v for k, v in byid.items() if len({(round(D[q+8],3), round(D[q+16],3), round(D[q+24],3)) for q in v}) > 1}
    kept_bad = 0; kinds = collections.Counter(); n_den = 0
    for k, v in conf.items():
        sig = []
        for q in v:
            xyz = (D[q+8], D[q+16], D[q+24])
            dn = any(denorm(x) for x in xyz)
            sig.append((data[q-1], int(I[q+4]), dn))
        kinds[tuple(sorted(sig))] += 1
        last = v[-1]
        if any(denorm(x) for x in (D[last+8], D[last+16], D[last+24])) or data[last-1] != 4: kept_bad += 1
    allden = sum(1 for q in pts_off if any(denorm(D[int(q)+k]) for k in (8,16,24)))
    allpre0 = sum(1 for q in pts_off if data[int(q)-1] != 4)
    print('==', os.path.basename(f)[:12], 'point recs', len(pts_off), 'distinct ids', len(byid), 'prefix', pre.most_common(5),
          '| denormal recs', allden, 'prefix!=4 recs', allpre0, '| conflicting ids', len(conf), 'kept copy bad', kept_bad)
    print('   copy signatures (prefix, vis, denormal):', kinds.most_common(6))
