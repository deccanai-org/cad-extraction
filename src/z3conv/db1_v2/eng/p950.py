import sys, numpy as np, collections
sys.path.insert(0, 'src'); sys.path.insert(0, '.')
import cache_eng
from db1dec import PLATE1_RE, SENTINEL
data, db, pts, cs, lay, M = cache_eng.get('data/9.50_unapproved_engine_011ad596ea.db1', '9.50')
cp = [m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
TY = int(sys.argv[1]) if len(sys.argv) > 1 else 345
tv = collections.Counter(); ok = 0; tot = 0; ex = []; multi = 0; nz = collections.Counter(); bad = []
for m in cp:
    k = int(db.I([m['off'] + 29])[0]); r1 = int(db.lookup([k], 33)[0])
    if r1 < 0: continue
    k2 = int(db.I([r1 + 25])[0]); recs = db.lookup_all(k2, 465)
    if not recs: continue
    if len(recs) > 1: multi += 1
    r = recs[0]
    u = db.D(r + 25 + 8 * np.arange(10)); v = db.D(r + 105 + 8 * np.arange(10)); ty = db.I(r + TY + 4 * np.arange(10))
    e = np.nonzero(ty == SENTINEL)[0]; n = int(e[0]) if len(e) else 10
    nz[n] += 1
    if n < 3: bad.append((m['prof'], ty.tolist())); continue
    tot += 1
    ext = u[:n].max() - u[:n].min()
    ok += abs(ext - m['L']) < 0.05 or abs(u[1] - m['L']) < 0.05
    for t in ty[:n]: tv[int(t)] += 1
    if any(t in (10, 20, 40) for t in ty[:n]) and len(ex) < 4:
        cx = db.D(r + 185 + 8 * np.arange(10)); cy = db.D(r + 265 + 8 * np.arange(10))
        ex.append((m['prof'], round(m['L'], 1), n, np.round(u[:n], 1).tolist(), np.round(v[:n], 1).tolist(), ty[:n].tolist(), np.round(cx[:n], 2).tolist(), np.round(cy[:n], 2).tolist()))
print('plates', len(cp), 'outline recs n>=3', tot, 'extent==L', ok, 'multi-record', multi, 'n dist', sorted(nz.items()), 'type values', tv.most_common(8))
print('bad', bad[:3])
for x in ex: print(x)
print('---- raw region for chamfered examples')
k_ = 0
for m in cp:
    k = int(db.I([m['off'] + 29])[0]); r1 = int(db.lookup([k], 33)[0])
    if r1 < 0: continue
    k2 = int(db.I([r1 + 25])[0]); recs = db.lookup_all(k2, 465)
    if not recs: continue
    r = recs[0]; ty = db.I(r + 345 + 4 * np.arange(10)); e = np.nonzero(ty == SENTINEL)[0]; n = int(e[0]) if len(e) else 10
    if not any(t in (10, 20) for t in ty[:n]): continue
    k_ += 1
    if k_ > 4: break
    print(m['prof'], 'types', ty[:n].tolist())
    print('  f32 185..345', [(185 + 4 * i, round(float(x), 3)) for i, x in enumerate(db.F(r + 185 + 4 * np.arange(40))) if np.isfinite(x) and 1e-3 < abs(x) < 1e5])
    print('  f64 185..345', [(185 + 8 * i, round(float(x), 3)) for i, x in enumerate(db.D(r + 185 + 8 * np.arange(20))) if np.isfinite(x) and 1e-3 < abs(x) < 1e5])
    print('  f64 385..465', [(385 + 8 * i, round(float(x), 3)) for i, x in enumerate(db.D(r + 385 + 8 * np.arange(10))) if np.isfinite(x) and 1e-3 < abs(x) < 1e5])
    print('  f64 181..', [(181 + 8 * i, round(float(x), 3)) for i, x in enumerate(db.D(r + 181 + 8 * np.arange(20))) if np.isfinite(x) and 1e-3 < abs(x) < 1e5])
