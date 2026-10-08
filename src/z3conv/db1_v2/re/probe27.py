import sys, numpy as np, collections, re
from cache import *
db, pts, cs, lay, M = get(sys.argv[1])
mm = [m for m in M if m['prof'] and m['prof'].startswith('MM')]
print(len(mm), collections.Counter(m['prof'] for m in mm).most_common(8))
S = lay['attr_stride']
for m in mm[:2]:
    for o in db.attr_records(lay, m['attr'])[:1]:
        raw = db.b[o:o + S]
        print(m['prof'], 'ints', [(j, int(x)) for j, x in zip(range(9, 60, 4), db.I(o + np.arange(9, 60, 4)))])
        print('   strs', [(mm_.start(), mm_.group().decode('latin1')) for mm_ in re.finditer(rb'[\x20-\x7e]{3,}', raw)])
        print('   floats', [(j, round(float(x), 3)) for j, x in zip(range(9, S - 3), db.F(o + np.arange(9, S - 3))) if np.isfinite(x) and 0.01 < abs(x) < 1e6 and abs(x * 100 - round(x * 100)) < 1e-3][:30])
