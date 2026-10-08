import sys, os, time, csv, random, collections
sys.path.insert(0, sys.argv[1])
import numpy as np, brep
job = sys.argv[2]; skp = sys.argv[3]; N = int(sys.argv[4])
sids = sorted({int(r['piece']) for r in csv.DictReader(open(skp)) if r['reason'] == 'reference_time_budget_exceeded'})
random.seed(1); sample = random.sample(sids, min(N, len(sids)))
C = collections.Counter(); ex = []
for sid in sample:
    b = open(os.path.join(job, 'subm', str(sid)), 'rb').read()
    r = brep.parse(b) or brep.parse(b, *brep.LAYOUTS[0], nvmin=3)
    if r is None: continue
    V, F = r
    if brep._solid_parts(V, F) is not None: continue
    rep = np.arange(len(V)); key = {}
    for i, p in enumerate(np.round(V / 1e-4).astype(np.int64)):
        rep[i] = key.setdefault(tuple(p), i)
    E = collections.Counter(); nl = 0
    for f in F:
        ls = brep.loops_of([int(rep[i]) for i in f]); nl += len(ls)
        for l in ls:
            for a, c in zip(l, l[1:] + l[:1]):
                if a != c: E[(min(a, c), max(a, c))] += 1
    use = collections.Counter(min(v, 5) for v in E.values())
    Fc, ndeg, ndup = brep.clean_faces(V, F)
    nb = len(brep.bodies(F))
    used = sorted({i for f in F for i in f}); ext = np.ptp(V[used], 0)
    k = ('free' if use.get(1) else 'nofree', 'nonmanifold' if (use.get(3) or use.get(4) or use.get(5)) else 'manifold', 'dup' if ndup else '', 'deg' if ndeg else '', 'flat' if ext.min() < 1e-4 else '', 'multibody' if nb > 1 else '')
    C[k] += 1
    if len(ex) < 8: ex.append((sid, len(V), len(F), dict(use), ndeg, ndup, nb, np.round(ext, 2).tolist()))
print(C.most_common()); print(ex)
