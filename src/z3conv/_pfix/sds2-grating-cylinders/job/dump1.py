import sys, os, json, collections
import numpy as np
sys.path.insert(0, sys.argv[1] + '/decode')
import brep
job, sid = sys.argv[2], int(sys.argv[3])
V, F = brep.parse(open(os.path.join(job, 'subm', str(sid)), 'rb').read())
F2 = brep.conform(V, F)
for lab, FF in (('raw', F), ('conform', F2)):
    E = collections.Counter()
    for f in FF:
        for l in brep.loops_of(f):
            for a, b in zip(l, l[1:] + l[:1]):
                if a != b: E[(min(a, b), max(a, b))] += 1
    free = [e for e, c in E.items() if c == 1]
    print(lab, 'faces', len(FF), 'edge use', dict(collections.Counter(E.values())))
    adj = collections.defaultdict(list)
    for a, b in free: adj[a].append(b); adj[b].append(a)
    print('  free-vertex degrees', dict(collections.Counter(len(v) for v in adj.values())))
    pts = sorted({i for e in free for i in e})
    P = V[pts]
    print('  free pts bbox', np.round(P.min(0), 4).tolist(), np.round(P.max(0), 4).tolist())
    for e in free[:12]:
        print('   ', e, np.round(V[e[0]], 4).tolist(), np.round(V[e[1]], 4).tolist(), round(float(np.linalg.norm(V[e[0]] - V[e[1]])), 5))
used = sorted({i for f in F for i in f})
print('used', len(used), 'ptp', np.round(np.ptp(V[used], 0), 4).tolist(), 'lo', np.round(V[used].min(0), 4).tolist())
for k, f in enumerate(F):
    if len(f) != 4:
        print('face', k, len(f), np.round(V[f].mean(0), 4).tolist())
