import sys, json, time, collections, numpy as np, re
sys.path.insert(0, 'src')
import db1dec; from db1dec import *
L = json.load(open('src/layouts.json'))
f = sys.argv[1]
data = load(f); db = Db(data); db.segment()
cand = dict(L['9.08']['layout']); cand.update(attr_stride=381, prof_off=125, rest_ref=189, rest_stride=54, rest_off=25)
pts = db.find_points(fixed=(cand['pts_stride'], cand['pts_k'])); cs = db.find_csys(only=(61, 9))
lay = dict(cand); lay['pts'] = 0; db._member_run = db.bystride[73]
M = members(db, pts, cs, lay)
print('members', len(M), 'prof', sum(1 for m in M if m['prof']), 'accept', db1dec._accept(db, lay, M), 'axis', db1dec._axis_agreement(db, pts, lay, M))
print(collections.Counter(m['prof'] for m in M).most_common(20))
noprof = [m for m in M if not m['prof']]
print('attr strides of noprof', collections.Counter(int(db.lookup_stride([m['attr']])[0]) for m in noprof[:3000]).most_common(5))
a = [m for m in noprof if int(db.lookup_stride([m['attr']])[0]) == 381][:3]
for m in a:
    o = db.attr_records(lay, m['attr'])[0]
    print('noprof attr strings', [(mm.start(), mm.group().decode('latin1')) for mm in re.finditer(rb'[\x20-\x7e]{2,}', db.b[o:o + 381])][:12])
db.find_polygons(lay, M); print('poly', {k: lay.get(k) for k in ('poly_field', 'poly_stride', 'poly_field2', 'poly_stride2', 'poly_ub', 'poly_vb', 'poly_cap', 'poly_frac', 'poly_ch')})
cp = [m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
print('contour plates', len(cp), 'with polygon', sum(1 for m in cp if db.polygon(lay, m)))
offs = np.array([m['off'] for m in cp[:500]])
for fld in (29,):
    v = db.I(offs + fld); print('field', fld, collections.Counter(int(x) for x in db.lookup_stride(v)).most_common(4))
