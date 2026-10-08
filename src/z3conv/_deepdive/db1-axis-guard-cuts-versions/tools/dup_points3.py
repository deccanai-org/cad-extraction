"""Per file: point records split into 'clean' (no denormal coordinate) vs 'garbage' (a denormal double = random bytes);
ids whose only clean copy is overridden by a garbage copy (db1old keeps the LAST record per id)."""
import sys, os, re, collections, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'kit_snapshot'))
import db1old
from db1dec import load
def bad(D, q): return any((D[q+k] != 0 and abs(D[q+k]) < 1e-100) for k in (8, 16, 24))
for f in sys.argv[1:]:
    data = load(f)
    eng = re.search(rb'(\d+\.\d+)', data[:16]).group(1).decode()
    if float(eng) >= 7.5: print('==', os.path.basename(f)[:12], eng, 'not old format'); continue
    o = db1old.Old(data); I = o.I_all; D = o.D_all
    N = len(I) - 400
    pv = np.zeros(N, bool)
    pv[:N - 32] = (I[:N - 32] > 0) & (I[4:N - 28] >= 0) & (I[4:N - 28] <= 64)
    for k in (8, 16, 24):
        v = D[k:N - 32 + k]; pv[:N - 32] &= np.isfinite(v) & (np.abs(v) < 1e8)
    pts_off = [int(q) for q in o.runs(pv, 33)]
    g = [q for q in pts_off if bad(D, q)]
    pre_clean = collections.Counter(data[q-1] for q in pts_off if not bad(D, q))
    pre_bad = collections.Counter(data[q-1] for q in g)
    vis_clean = collections.Counter(int(I[q+4]) for q in pts_off if not bad(D, q))
    vis_bad = collections.Counter(int(I[q+4]) for q in g)
    byid = collections.defaultdict(list)
    for q in pts_off: byid[int(I[q])].append(q)
    clobber = sum(1 for k, v in byid.items() if bad(D, v[-1]) and any(not bad(D, q) for q in v))
    multi_clean = sum(1 for k, v in byid.items() if len({(D[q+8], D[q+16], D[q+24]) for q in v if not bad(D, q)}) > 1)
    print('==', os.path.basename(f)[:12], eng, 'recs', len(pts_off), 'garbage(denormal)', len(g), '| clean prefix', pre_clean.most_common(4), 'garbage prefix', pre_bad.most_common(4),
          '| clean vis', vis_clean.most_common(4), 'garbage vis', vis_bad.most_common(3), '| ids clobbered by garbage', clobber, '| ids with >1 distinct clean coords', multi_clean)
