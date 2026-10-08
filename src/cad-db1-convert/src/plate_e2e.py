"""end-to-end plate check: every Tekla IfcPlate (truth) vs our written IfcPlates -
reproduced when all its solid corners are within 1 mm of one of our plate solids' corners."""
import sys, pickle, collections, numpy as np

class cKDTree:
    # tiny spatial hash (no scipy on this box): nearest point within 2 mm cells
    def __init__(self, X, h=2.0):
        self.X = X; self.h = h; self.g = collections.defaultdict(list)
        for i, k in enumerate(map(tuple, np.floor(X / h).astype(np.int64))): self.g[k].append(i)
    def query(self, V):
        D = []; J = []
        for q in V:
            k = np.floor(q / self.h).astype(np.int64); best = (np.inf, -1)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for i in self.g.get((k[0] + dx, k[1] + dy, k[2] + dz), ()):
                            d = float(np.linalg.norm(self.X[i] - q))
                            if d < best[0]: best = (d, i)
            D.append(best[0]); J.append(best[1])
        return np.array(D), np.array(J)
truth = [p for p in pickle.load(open(sys.argv[1], 'rb')) if p['cls'] == 'IfcPlate']
ours = [p for p in pickle.load(open(sys.argv[2], 'rb')) if p['cls'] == 'IfcPlate']
def corners(p):
    P = p['pts'][:-1] if np.linalg.norm(p['pts'][0] - p['pts'][-1]) < 1e-6 else p['pts']
    n = p['n'] / np.linalg.norm(p['n'])
    return np.concatenate([P, P + n * p['t']])
C = [corners(p) for p in ours]; own = np.concatenate([[i] * len(c) for i, c in enumerate(C)]); tree = cKDTree(np.concatenate(C))
res = collections.Counter(); used = set(); bad = []
for p in truth:
    V = corners(p); d, j = tree.query(V)
    if d.max() < 1.0:
        k = collections.Counter(own[j]).most_common(1)[0][0]
        res['reproduced'] += 1; used.add(k)
    elif (d < 1.0).mean() >= 0.5: res['partial'] += 1; bad.append((p['prof'], round(float(d.max()), 1), len(V)//2))
    else: res['missing'] += 1
print('truth IfcPlate', len(truth), 'ours', len(ours), dict(res), 'our plates matched', len(used))
print('partial examples', bad[:10])
