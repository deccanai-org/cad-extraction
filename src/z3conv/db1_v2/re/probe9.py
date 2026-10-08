import sys, numpy as np, collections
from bolt853 import *
db, pts, cs, lay, M, seqs, pairs = setup(*sys.argv[1:3])
n = 0
for g, m in pairs:
    P = positions(db, m); T = truth_local(g, m); c, d = classify(P, T)
    if c != 'translated': continue
    n += 1
    if n > 6: break
    print('\n', g['guid'][:8], 'offset', np.round(d, 2), 'memL', round(m['L'], 2), 'n', len(P), 'P', [tuple(np.round(p[:2], 1)) for p in P][:3], 'T', T[:3].round(1).tolist())
    o = m['off']; print('   member doubles', [round(float(x), 3) for x in db.D(o + 41 + 8 * np.arange(4))], 'ints', [int(x) for x in db.I(o + np.arange(9, 41, 4))], 'tail', db.b[o + 73 - 0: o + 73][:0])
    for r in recs341(db, m):
        F = db.F(r + 17 + 4 * np.arange(80))
        print('   341 nonzero floats', [(17 + 4 * i, round(float(x), 3)) for i, x in enumerate(F) if np.isfinite(x) and 1e-3 < abs(x) < 1e7])
        I = db.I(r + 9 + 4 * np.arange(82)); print('   341 ints nonzero', [(9 + 4 * i, int(x)) for i, x in enumerate(I) if x != 0 and not (1e-3 < abs(float(np.frombuffer(np.int32(x).tobytes(), '<f4')[0])) < 1e7)][:20])
    # pts p1 p2
    P_ = pts[lay['pts']]
    p1 = db._pt(P_, db.I([o + lay['p1']]))[0]; p2 = db._pt(P_, db.I([o + lay['p2']]))[0]
    z = np.cross(m['x'], m['y'])
    print('   p1 local', np.round([(p1 - m['O']) @ m['x'], (p1 - m['O']) @ m['y'], (p1 - m['O']) @ z], 2), 'p2 local', np.round([(p2 - m['O']) @ m['x'], (p2 - m['O']) @ m['y'], (p2 - m['O']) @ z], 2))
