"""Where do the conflicting duplicate point ids live? List every stride-33 point record per duplicated id with its run context."""
import sys, os, re, collections, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'kit_snapshot'))
import db1old
from db1dec import load
f = sys.argv[1]; want = [int(x) for x in sys.argv[2:]]
data = load(f)
o = db1old.Old(data); I = o.I_all; D = o.D_all
N = len(I) - 400
pv = np.zeros(N, bool)
pv[:N - 32] = (I[:N - 32] > 0) & (I[4:N - 28] >= 0) & (I[4:N - 28] <= 64)
for k in (8, 16, 24):
    v = D[k:N - 32 + k]; pv[:N - 32] &= np.isfinite(v) & (np.abs(v) < 1e8)
pts_off = o.runs(pv, 33)
# group into runs
runs = []; cur = [int(pts_off[0])]
for q in pts_off[1:]:
    q = int(q)
    if q - cur[-1] == 33: cur.append(q)
    else: runs.append(cur); cur = [q]
runs.append(cur)
run_of = {}
for ri, r in enumerate(runs):
    for q in r: run_of[q] = ri
print('point runs', len(runs), [(r[0], len(r)) for r in runs[:40]])
byid = collections.defaultdict(list)
for q in pts_off: byid[int(I[q])].append(int(q))
dups = {k: v for k, v in byid.items() if len(v) > 1}
print('ids with >1 record', len(dups))
conf = {k: v for k, v in dups.items() if len({(round(D[q+8],3), round(D[q+16],3), round(D[q+24],3)) for q in v}) > 1}
print('ids with conflicting coords', len(conf))
# which runs hold the conflicting copies
rc = collections.Counter()
for k, v in conf.items():
    for q in v: rc[run_of[q]] += 1
print('runs holding conflicting copies:', [(ri, runs[ri][0], len(runs[ri]), n) for ri, n in rc.most_common(10)])
for k in want:
    print('id', k)
    for q in byid.get(k, []):
        ri = run_of[q]
        print('   off', q, 'byte0', data[q-1], 'vis', int(I[q+4]), 'xyz', D[q+8], D[q+16], D[q+24], 'run', ri, 'run_start', runs[ri][0], 'run_len', len(runs[ri]), 'idx_in_run', runs[ri].index(q))
# zero-coordinate points in conflicting set
z = sum(1 for k, v in conf.items() if any(D[q+8] == 0 and D[q+16] == 0 and D[q+24] == 0 for q in v))
print('conflicting ids with an all-zero copy:', z, 'of', len(conf))
# last copy zero?
lz = sum(1 for k, v in conf.items() if D[v[-1]+8] == 0 and D[v[-1]+16] == 0 and D[v[-1]+24] == 0)
print('conflicting ids whose LAST copy (the one db1old keeps) is all-zero:', lz)
