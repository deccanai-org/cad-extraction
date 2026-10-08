import sys, numpy as np, collections
from bolt853 import *
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M, seqs, pairs = setup(db1, ifc)
S = int(db.lookup_stride([pairs[0][1]['attr']])[0]); print('attr stride', S)
hitF = collections.defaultdict(collections.Counter); hitD = collections.defaultdict(collections.Counter); hitI = collections.defaultdict(collections.Counter)
n = 0
for g, m in pairs:
    rr = db.attr_records(lay, m['attr'])
    if not rr: continue
    a = rr[0]; n += 1; ps = g['pset']
    tv = dict(d=g['d'], L=g['L'], hole=ps.get('Bolt hole diameter'), tol=(ps.get('Bolt hole diameter') or 0) - g['d'], sx=ps.get('Slotted hole x'), sy=ps.get('Slotted hole y'),
              nb=len(g['bolts']), wc=ps.get('Washer count'), nc=ps.get('Nut count'))
    F = db.F(a + np.arange(S - 3)); D = db.D(a + np.arange(S - 7)); I = db.I(a + np.arange(S - 3))
    for nm, t in tv.items():
        if t is None or (isinstance(t, float) and t == 0): continue
        for k in np.nonzero(np.isfinite(F) & (np.abs(F - t) < 0.051))[0]: hitF[nm][int(k)] += 1
        for k in np.nonzero(np.isfinite(D) & (np.abs(D - t) < 0.051))[0]: hitD[nm][int(k)] += 1
        if float(t).is_integer():
            for k in np.nonzero(I == int(t))[0]: hitI[nm][int(k)] += 1
print('pairs with attr', n)
for nm in ('d', 'L', 'hole', 'tol', 'sx', 'sy', 'nb', 'wc', 'nc'):
    print(nm, 'F', hitF[nm].most_common(4), 'D', hitD[nm].most_common(3), 'I', hitI[nm].most_common(3))
# member record: same search
print('--- member record')
hitF = collections.defaultdict(collections.Counter)
for g, m in pairs:
    o = m['off']; F = db.F(o + np.arange(73 - 3)); D = db.D(o + np.arange(73 - 7)); ps = g['pset']
    for nm, t in dict(d=g['d'], L=g['L'], sx=ps.get('Slotted hole x'), sy=ps.get('Slotted hole y')).items():
        if not t: continue
        for k in np.nonzero(np.isfinite(D) & (np.abs(D - t) < 0.051))[0]: hitF[nm][('D', int(k))] += 1
        for k in np.nonzero(np.isfinite(F) & (np.abs(F - t) < 0.051))[0]: hitF[nm][('F', int(k))] += 1
for nm, c in hitF.items(): print(nm, c.most_common(4))
