"""All stride-333 polygon records for the polygon id of a given part (old engines), to see whether stray copies shadow the real one."""
import sys, os, re, numpy as np
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(H, '..', 'kit_snapshot'))
import db1old
from db1dec import load
f = sys.argv[1]; pids = [int(x) for x in sys.argv[2:]]
data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
o = db1old.Old(data); I = o.I_all; F = o.F_all; N = len(I) - 400
P = db1old.PART_NEW if eng >= 7.1 else db1old.PART_OLD
M, info, cut_rel = db1old.read(data, eng)
gv = np.zeros(N, bool); Mx = N - 340
gv[:Mx] = (I[:Mx] > 0) & (I[4:Mx + 4] >= 0) & (I[4:Mx + 4] <= 64)
for k in range(12, 132, 4):
    v = F[k:Mx + k]; gv[:Mx] &= np.isfinite(v) & (np.abs(v) < 1e7)
pg_off = [int(q) for q in o.runs(gv, 333)]
byid = {}
for q in pg_off: byid.setdefault(int(I[q]), []).append(q)
dups = {k: v for k, v in byid.items() if len(v) > 1}
print('polygon recs', len(pg_off), 'ids', len(byid), 'ids with >1 record', len(dups), 'max copies', max((len(v) for v in byid.values()), default=0))
# no-field distribution for duplicates
for pid in pids:
    m = next(m for m in M if m['pid'] == pid)
    q = m['off']; gid = int(I[q + P['poly']])
    print('part', pid, m['prof'], 'poly id', gid, 'npoints attr', 'records', len(byid.get(gid, [])))
    for r in byid.get(gid, []):
        xs = [round(float(F[r + 12 + 4*i]), 2) for i in range(10)]; ys = [round(float(F[r + 52 + 4*i]), 2) for i in range(10)]; zs = [round(float(F[r + 92 + 4*i]), 2) for i in range(10)]
        print('   off', r, 'prefix', data[r-1], 'no', int(I[r+4]), 'x', xs[:6], 'y', ys[:6], 'z', zs[:6])
    # also raw search: every offset where int == gid followed by small no, not in pg_off
    raw = np.nonzero(I[:N] == gid)[0]
    print('   raw int occurrences of poly id:', len(raw), [(int(x), data[int(x)-1], int(I[int(x)+4])) for x in raw[:20]])
