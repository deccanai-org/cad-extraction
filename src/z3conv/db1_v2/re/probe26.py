"""scan runs for bolt-group records (member-like records whose attr ref -> record with obj_type 10)"""
import sys, numpy as np, collections
from cache import *
SENT = 2147483647
for p in sys.argv[1:]:
    db, pts, cs, lay, M = get(p)
    memoffs = set(m['off'] for m in M)
    print(p.split('/')[-1], db.b[7:12], 'lay stride', lay.get('stride'), 'attr', lay.get('attr_stride'))
    res = collections.Counter()
    for s, recs in db.bystride.items():
        if s < 45 or s > 200 or len(recs) < 3: continue
        for af in (13,):
            a = db.I(recs + af); st = db.lookup_stride(a)
            for S in set(st.tolist()):
                if S <= 0: continue
                sel = recs[st == S]; aa = a[st == S]
                ao = db.lookup(aa, S)
                ob = db.I(ao + 13)
                n10 = int((ob == 10).sum())
                if n10 >= 3: res[(s, af, S, 'obj10')] += n10
    print('   ', res.most_common(8))
