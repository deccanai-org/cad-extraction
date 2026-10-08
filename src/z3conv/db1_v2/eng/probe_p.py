import sys, json, time, collections, numpy as np
sys.path.insert(0, 'src')
import db1dec; from db1dec import *
L = json.load(open('src/layouts.json'))
f = sys.argv[1]
data = load(f); db = Db(data); db.segment()
t = time.time(); pts, cs, lay = db1dec._semi(db, L['9.08']['layout']); print('semi', round(time.time() - t, 1))
print({k: v for k, v in (lay or {}).items()})
if lay and lay.get('attr_stride'):
    M = members(db, pts, cs, lay)
    print('members', len(M), 'prof', sum(1 for m in M if m['prof']), 'accept', db1dec._accept(db, lay, M), 'axis', db1dec._axis_agreement(db, pts, lay, M))
    db.find_polygons(lay, M); print('poly', {k: lay.get(k) for k in ('poly_field', 'poly_stride', 'poly_field2', 'poly_stride2', 'poly_ub', 'poly_vb', 'poly_cap', 'poly_frac', 'poly_ch')})
    print(collections.Counter(m['prof'] for m in M).most_common(25))
