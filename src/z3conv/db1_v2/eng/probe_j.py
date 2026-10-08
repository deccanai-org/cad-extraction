import sys, json, time, collections, numpy as np, re
sys.path.insert(0, 'src')
from db1dec import *
f = sys.argv[1]
data = load(f); db = Db(data); db.segment()
r41 = [(s, r) for s, r in db.runs if s == 41]
print('runs41', len(r41), 'lens', sorted([len(r) for s, r in r41], reverse=True)[:10])
for s, r in sorted(r41, key=lambda x: -len(x[1]))[:4]:
    x, y, z, ok = db._xyz(r[:64], 17); print(' run len', len(r), 'plaus@17', ok.mean(), 'sample', np.round(np.c_[x, y, z][:3], 1).tolist(), 'ints', db.I(r[:3, None] + np.arange(9, 41, 4)).tolist())
for S in (648, 73, 56):
    recs = db.bystride.get(S)
    for o in recs[:2]:
        print(S, 'ints', db.I(o + np.arange(9, min(S, 120), 4)).tolist())
        print('   strs', [(mm.start(), mm.group().decode('latin1')) for mm in re.finditer(rb'[\x20-\x7e]{3,}', db.b[o:o + S])][:10])
