"""fitrec_probe.py NAME : layout of old-engine fitting (type 9) / line cut (type 12) child records: unit vectors, csa-key ints,
neighbouring records (same id, other strides), for parts whose Tekla Length tells where the fitted end is."""
import sys, os, re, collections, numpy as np
W = '/work/agentwork/cut-not-applied'; NAME = sys.argv[1]
sys.path.insert(0, W + '/kitnp')
import db1old
from db1dec import load
np.set_printoptions(suppress=True, precision=4, linewidth=250)
src = f'{W}/truth/{NAME}.db1' if os.path.exists(f'{W}/truth/{NAME}.db1') else f'{W}/src/{NAME}.db1'
data = load(src); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng); byp = {m['pid']: m for m in M}
o = db1old.Old(data); I = o.I_all; D = o.D_all; N = len(I) - 400; u8 = o.u8
cv = np.zeros(N, bool); Mx = N - 60
x = np.stack([D[k:Mx + k] for k in (0, 8, 16)], 1); y = np.stack([D[k:Mx + k] for k in (24, 32, 40)], 1)
with np.errstate(invalid='ignore', over='ignore'):
    cv[:Mx] = (np.abs((x * x).sum(1) - 1) < 0.02) & (np.abs((y * y).sum(1) - 1) < 0.02) & (I[48:Mx + 48] > 0)
cs_off = o.runs(cv, 53); csa = {int(I[q + 48]): q for q in cs_off}
# any 'unit vector pair' records (not only in runs) keyed at other offsets
del x, y
rv = np.zeros(N, bool); Mr = N - 20
rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
rel = collections.defaultdict(list)
for rs in (17, 61):
    for q in o.runs(rv, rs):
        if int(I[q + 4]) in (9, 12): rel[int(I[q + 4])].append((int(I[q + 8]), int(I[q + 12]), rs))
print('==', NAME, eng, {k: len(v) for k, v in rel.items()}, 'csa', len(csa))
def recs(cid):
    return [int(q) for q in np.nonzero(I[:N] == cid)[0] if u8[int(q) - 1] == 4]
def unitvecs(q, span=400):
    out = []
    for k in range(4, span, 4):
        v = D[q + k:q + k + 24:8]
        if len(v) == 3 and np.all(np.isfinite(v)) and abs(float(v @ v) - 1) < 1e-6 and np.max(np.abs(v)) <= 1: out.append((k, np.round(v, 4)))
    return out
for T in (9, 12):
    stride_c = collections.Counter(); key_hits = collections.Counter(); uv_off = collections.Counter(); nrec = 0
    for a, b, rs in rel.get(T, [])[:400]:
        qs = recs(b)
        qs = [q for q in qs if np.all(np.isfinite(D[q + 8:q + 32:8])) and np.all(np.abs(D[q + 8:q + 32:8]) < 1e8) and np.any(D[q + 8:q + 32:8] != 0)]
        if not qs: continue
        q = qs[0]; nrec += 1
        for k in range(4, 200, 4):
            if int(I[q + k]) in csa: key_hits[k] += 1
        for k, v in unitvecs(q): uv_off[k] += 1
        # distance to the previous / next live record with an id in the same child id range -> stride
        for d in range(20, 400):
            if u8[q + d - 1] == 4 and abs(int(I[q + d]) - b) < 50000 and int(I[q + d]) > 0 and np.all(np.isfinite(D[q + d + 8:q + d + 32:8])) and np.all(np.abs(D[q + d + 8:q + d + 32:8]) < 1e8) and np.any(D[q + d + 8:q + d + 32:8] != 0):
                stride_c[d] += 1; break
    print(f' type {T}: child records {nrec} csa-key int offsets {key_hits.most_common(6)} unit-vector offsets {uv_off.most_common(8)} next-record distance {stride_c.most_common(5)}')
    for a, b, rs in rel.get(T, [])[:4]:
        m = byp.get(a); qs = recs(b)
        if not qs or not m: continue
        q = qs[0]
        print('   part', a, m['prof'], 'O', np.round(m['O'], 2), 'x', np.round(m['x'], 4), 'L', round(m['L'], 2))
        print('     child', b, 'q', q, 'ints', [int(I[q + 4 * k]) for k in range(0, 24)])
        print('       dbl@8+8k', np.array([D[q + 8 + 8 * k] for k in range(0, 14)]))
        print('       dbl@4+8k', np.array([D[q + 4 + 8 * k] for k in range(0, 14)]))
        print('       f32@4k', np.array([o.F_all[q + 4 * k] for k in range(0, 24)]))
        print('       unit vectors', unitvecs(q))
        k4 = int(I[q + 4])
        if k4 in csa: c = csa[k4]; print('       csa[key4]', np.array([D[c + 8 * k] for k in range(6)]))
