import sys, json, time, collections, numpy as np
sys.path.insert(0, 'src')
import db1dec; from db1dec import *
L = json.load(open('src/layouts.json'))
f = sys.argv[1]
data = load(f); db = Db(data); db.segment()
pts, cs, lay = db1dec._semi(db, L['9.08']['layout'])
M = members(db, pts, cs, lay)
cp = [m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
print('contour plates', len(cp), collections.Counter(m['prof'] for m in cp).most_common(5))
offs = np.array([m['off'] for m in cp])
for fld in range(13, 41, 4):
    v = db.I(offs + fld); st = collections.Counter(int(x) for x in db.lookup_stride(v)); print('field', fld, st.most_common(4))
# follow +29 -> its record, and look for second hop
v = db.I(offs + 29)
for S in (33, 29, 37, 45):
    ro = db.lookup(v, S); ok = ro >= 0
    print('29 ->', S, ok.mean())
    if ok.mean() > 0.5:
        for g in range(9, S - 3, 4):
            v2 = db.I(ro[ok] + g); print('   hop field', g, collections.Counter(int(x) for x in db.lookup_stride(v2)).most_common(3))
