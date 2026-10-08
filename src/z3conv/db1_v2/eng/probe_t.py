import sys, json, collections, numpy as np
sys.path.insert(0, 'src'); sys.path.insert(0, '.')
import cache_eng
from db1dec import PLATE1_RE
data, db, pts, cs, lay, M = cache_eng.get(sys.argv[1], sys.argv[2])
print('members', len(M), {k: lay.get(k) for k in ('variant', 'attr_stride', 'poly_stride', 'poly_field2', 'poly_stride2', 'poly_frac')})
cp = [m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
print('contour plates', len(cp))
offs = np.array([m['off'] for m in cp[:400]]); Lm = np.array([m['L'] for m in cp[:400]])
for fld in range(13, 41, 4):
    v = db.I(offs + fld); print(' field', fld, collections.Counter(int(x) for x in db.lookup_stride(v)).most_common(3))
v = db.I(offs + 29)
for S in sorted(set(int(x) for x in db.lookup_stride(v)) - {-1}):
    ro = db.lookup(v, S); ok = ro >= 0
    if ok.mean() < 0.3: continue
    print(' 29 ->', S, round(ok.mean(), 2))
    for g in range(9, min(S, 80) - 3, 4):
        v2 = db.I(ro[ok] + g); c = collections.Counter(int(x) for x in db.lookup_stride(v2)).most_common(3)
        if c and c[0][0] > 0: print('    hop field', g, c)
    r = db._uv_detect(ro[ok], Lm[ok], S); print('    uv direct', r)
