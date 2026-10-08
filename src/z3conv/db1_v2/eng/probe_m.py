import sys, collections, numpy as np
sys.path.insert(0, 'src')
from db1dec import *
f = sys.argv[1]
data = load(f); db = Db(data); db.segment()
r41 = sorted([(s, r) for s, r in db.runs if s == 41], key=lambda x: -len(x[1]))
print('runs41', len(r41), [len(r) for s, r in r41[:10]])
for s, r in r41[:4]:
    x, y, z, ok = db._xyz(r[:64], 17); xa, ya, za, oka = db._xyz(r, 17)
    print('run', len(r), 'first64 ok', ok.mean(), 'all ok', oka.mean(), 'first bad idx', np.nonzero(~oka)[0][:10])
    for i in np.nonzero(~oka)[0][:3]:
        o = int(r[i]); print('   bad rec ints', db.I(o + np.arange(9, 41, 4)).tolist(), 'dbl', [float(v) for v in db.D(o + np.array([17, 25, 33]))])
# member p1/p2 keys: in which strides do they live?
m73 = db.bystride[73][:2000]
p1 = db.I(m73 + 21); st = collections.Counter(int(x) for x in db.lookup_stride(p1)); print('p1 key strides', st.most_common(5))
