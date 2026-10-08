import sys, numpy as np, re, collections
sys.path.insert(0, '/opt/db1v2/src')
from db1dec import *
db = Db(load(sys.argv[1])); db.segment()
print(db.b[:64])
for s in [int(x) for x in sys.argv[2:]]:
    recs = db.bystride.get(s, [])
    print('== stride', s, 'n', len(recs))
    for o in recs[:3]:
        o = int(o); raw = db.b[o:o + s]
        print('  ', raw[:s].hex(' '))
        print('     dbl', [round(float(db.D([o + k])[0]), 3) for k in range(13, s - 7, 4)][:14])
# most common printable strings overall
strs = collections.Counter(m.group().decode('latin1') for m in re.finditer(rb'[A-Z][A-Z0-9_ ]{3,20}\x00', db.b[:20_000_000]))
print(strs.most_common(25))
