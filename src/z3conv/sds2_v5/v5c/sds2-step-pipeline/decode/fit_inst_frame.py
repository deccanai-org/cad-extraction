"""Search the member-local axis convention for connection-material instances.

world = p1 + F @ S @ (Mx @ c + pos), F = [x u v] member frame columns, S = signed permutation (48 options),
Mx in {M, M.T}; c = subm bbox centre. Score = share of instances within 1in of an IFC connection part centroid.
"""
import sys, csv, itertools, random
import numpy as np
from scipy.spatial import cKDTree
from sds2job import read_members
import to_step as T
from instances import member_instances, subm_vertices

job, parts_csv, sx, sy = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
IN = 0.0254
P = np.array([[float(r["cx"]) / IN - sx, float(r["cy"]) / IN - sy, float(r["cz"]) / IN] for r in csv.DictReader(open(parts_csv))])
tree = cKDTree(P)
mems, _ = read_members(job)
random.seed(0)
cand = [m for m in mems if m.type in ("BEAM", "COLUMN", "VERTICAL BRACE")]
random.shuffle(cand)
samples = []
for m in cand[:1200]:
    fr = T.frame(m, "X")
    if fr is None: continue
    p1, x, u, v, L = fr
    F = np.c_[x, u, v]
    for sid, M, pos, R in member_instances(job, m.id)[1]:
        V = subm_vertices(job, sid)
        if V is None or len(V) < 4: continue
        samples.append((p1, F, M, pos, (V.min(0) + V.max(0)) / 2, m.type))
print("sample instances:", len(samples))
Ss = []
for perm in itertools.permutations(range(3)):
    for sg in itertools.product((1, -1), repeat=3):
        S = np.zeros((3, 3))
        for i, j in enumerate(perm): S[i, j] = sg[i]
        Ss.append(S)
results = []
for S in Ss:
    for tr in (False, True):
        W = np.array([p1 + F @ S @ ((M.T if tr else M) @ c + pos) for p1, F, M, pos, c, t in samples])
        d, _ = tree.query(W)
        results.append((np.mean(d < 1), np.median(d), tr, S))
results.sort(key=lambda r: -r[0])
for sc, med, tr, S in results[:5]:
    print(f"share<1in {sc:.3f} median {med:.2f} transpose={tr}\n{S.astype(int)}")
