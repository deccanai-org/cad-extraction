import sys, os, time, csv, random, collections
sys.path.insert(0, sys.argv[1])
import numpy as np, brep
job = sys.argv[2]; skp = sys.argv[3]; N = int(sys.argv[4])
sids = sorted({int(r['piece']) for r in csv.DictReader(open(skp)) if r['reason'] == 'reference_time_budget_exceeded'})
random.seed(1); sample = random.sample(sids, min(N, len(sids)))
T = collections.Counter(); C = collections.Counter(); slow = []
for sid in sample:
    b = open(os.path.join(job, 'subm', str(sid)), 'rb').read()
    t0 = time.time(); r = brep.parse(b) or brep.parse(b, *brep.LAYOUTS[0], nvmin=3); t1 = time.time(); T['parse'] += t1 - t0
    if r is None: C['no parse'] += 1; continue
    V, F = r
    if len(F) > 20000: C['over cap'] += 1; continue
    # raw edge stats
    E = collections.Counter()
    for f in F:
        for l in brep.loops_of(f):
            for a, c in zip(l, l[1:] + l[:1]): E[(min(a, c), max(a, c))] += 1
    free = sum(1 for v in E.values() if v == 1)
    t2 = time.time(); sh = brep._solid_parts(V, F); t3 = time.time(); T['first sew'] += t3 - t2
    if sh is not None: C['closed first pass'] += 1; continue
    t4 = time.time(); sh = brep.solid(V, F); t5 = time.time(); T['solid() total'] += t5 - t4
    if sh is not None: C['closed by repair'] += 1; continue
    t6 = time.time(); s2 = brep.shell(V, F); t7 = time.time(); T['shell'] += t7 - t6
    C['open'] += 1
    slow.append((round(t5 - t4, 2), sid, len(F), free, round(free / max(len(E), 1), 3)))
    C['open, raw free edges > 2%'] += free > 0.02 * len(E)
print('sampled', len(sample), 'of', len(sids))
print(dict(C)); print({k: round(v, 1) for k, v in T.items()})
slow.sort(reverse=True); print('slowest solid() on open parts', slow[:12])
fr = [s for s in slow if s[4] > 0.02]; print('open parts with >2% free edges: n', len(fr), 'solid() time', round(sum(s[0] for s in fr), 1), 'of', round(sum(s[0] for s in slow), 1))
