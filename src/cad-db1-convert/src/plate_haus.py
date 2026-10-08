"""plate boundary check, both directions: truth (Tekla IFC, arcs densified) vs ours (our IFC).
reproduced = both one-sided Hausdorff distances of the mid-plane boundary < tol."""
import sys, pickle, collections, numpy as np
tol = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
class Hash:
    def __init__(self, X, own, h=1.0):
        self.X = X; self.own = own; self.h = h; self.g = collections.defaultdict(list)
        for i, k in enumerate(map(tuple, np.floor(X / h).astype(np.int64))): self.g[k].append(i)
    def near(self, q):
        k = np.floor(q / self.h).astype(np.int64); best = (np.inf, -1)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for i in self.g.get((k[0] + dx, k[1] + dy, k[2] + dz), ()):
                        d = float(np.linalg.norm(self.X[i] - q))
                        if d < best[0]: best = (d, i)
        return best
def mid_samples(p, step=0.5):
    n = p['n'] / np.linalg.norm(p['n']); P = p['pts'] + n * p['t'] / 2
    if np.linalg.norm(P[0] - P[-1]) > 1e-6: P = np.vstack([P, P[:1]])
    out = []
    for a, b in zip(P[:-1], P[1:]):
        L = np.linalg.norm(b - a); k = max(1, int(np.ceil(L / step)))
        out += [a + (b - a) * t for t in np.arange(k) / k]
    return np.array(out)
truth = pickle.load(open(sys.argv[1], 'rb')); ours = pickle.load(open(sys.argv[2], 'rb'))
S = [mid_samples(p) for p in ours]
H = Hash(np.concatenate(S), np.concatenate([[i] * len(s) for i, s in enumerate(S)]))
import re
byk = collections.Counter()
res = collections.Counter(); arcres = collections.Counter(); worst = []
for p in truth:
    T = mid_samples(p); d = []; owners = collections.Counter()
    for q in T:
        dist, i = H.near(q); d.append(dist)
        if i >= 0: owners[H.own[i]] += 1
    d = np.array(d); frac = float(np.mean(d < tol))
    if not owners or frac < 0.5: res['missing'] += 1; byk[('missing', 'parametric' if re.search(r'[xX*]', p['prof'] or '') else 'contour')] += 1; continue
    HT = Hash(T, np.zeros(len(T), int)); cand = []
    for k, _ in owners.most_common(4):
        Hk = Hash(S[k], np.zeros(len(S[k]), int))
        fwd_k = max(Hk.near(q)[0] for q in T); back_k = max(HT.near(q)[0] for q in S[k])
        cand.append((max(fwd_k, back_k), fwd_k, back_k, k))
    _, fwd, back, k = min(cand)
    tag = 'reproduced' if max(fwd, back) < tol else 'deviates'
    res[tag] += 1; byk[(tag, 'parametric' if re.search(r'[xX*]', p['prof'] or '') else 'contour')] += 1
    if p.get('arcs'): arcres[tag] += 1
    if tag == 'deviates': worst.append((round(fwd, 2), round(back, 2), p['prof'], len(p['pts']), round(frac, 2), bool(ours[k].get('beam')), bool(p.get('arcs'))))
print('truth plates', len(truth), 'ours', len(ours), dict(res), ' arcs:', dict(arcres))
print('deviation examples (fwd, back):', sorted(worst, reverse=True)[:12])
print('deviation histogram', collections.Counter(min(8, int(min(99, max(w[0], w[1])))) for w in worst))


print('by name kind', sorted(byk.items()))
# ---- detail of a few deviating plates in the truth plate's own 2D frame
if len(sys.argv) > 4:
    shown = 0
    for p in truth:
        T = mid_samples(p); owners = collections.Counter(); d = []
        for q in T:
            dist, i = H.near(q); d.append(dist)
            if i >= 0: owners[H.own[i]] += 1
        d = np.array(d)
        if not owners or np.mean(d < tol) < 0.5 or d.max() < tol: continue
        if sys.argv[4] == 'arcs' and not p.get('arcs'): continue
        if sys.argv[4] == 'noarcs' and p.get('arcs'): continue
        k = owners.most_common(1)[0][0]; o = ours[k]
        n = p['n'] / np.linalg.norm(p['n']); O = p['pts'][0] + n * p['t'] / 2
        ex = p['pts'][1] - p['pts'][0]; ex -= n * (n @ ex); ex /= np.linalg.norm(ex); ey = np.cross(n, ex)
        f2 = lambda Q: [(round(float((q - O) @ ex), 1), round(float((q - O) @ ey), 1)) for q in Q]
        no = o['n'] / np.linalg.norm(o['n'])
        print('TRUTH', p['prof'], 't', round(p['t'], 2), f2(p['pts'] + n * p['t'] / 2)[:50])
        print('OURS ', 't', round(o['t'], 2), 'n.n', round(float(n @ no), 3), f2(o['pts'] + no * o['t'] / 2)[:50])
        shown += 1
        if shown >= int(sys.argv[5]): break
