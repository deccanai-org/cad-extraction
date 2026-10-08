import sys, re, collections, numpy as np
sys.path.insert(0, '/opt/db1v2/src3')
from db1dec import *
db = Db(load(sys.argv[1])); db.segment()
b = db.b
# locate every occurrence of a known part name and look at the spacing / header before it
pos = [m.start() for m in re.finditer(rb'(PERIMETER_BEAM|PLATE|CUTPART|BEAM|COLUMN)\x00', b)]
print('name hits', len(pos))
d = collections.Counter(pos[i + 1] - pos[i] for i in range(len(pos) - 1)); print('spacing', d.most_common(8))
for p in pos[:6]:
    # find the header (tag 04) before the name
    hs = [k for k in range(5, 120) if b[p - k] == 4 and int(db.I([p - k - 8])[0]) > 0]
    print(p, repr(b[p:p + 16]), 'tag04 back at', hs[:4])
print('runs with stride in 320-360:', collections.Counter(s for s, r in db.runs if 320 <= s <= 360))
