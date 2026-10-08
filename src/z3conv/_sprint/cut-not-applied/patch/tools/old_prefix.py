"""prefix byte (record liveness) of type-11 relation records and of the cut part records, split by parent decoded / not."""
import sys, os, re, json, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old
from db1dec import load
for f in sys.argv[2:]:
    data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info, cut_rel = db1old.read(data, eng)
    byp = {m['pid']: m for m in M}
    o = db1old.Old(data); I = o.I_all; N = len(I) - 400
    rv = np.zeros(N, bool); Mr = N - 20
    rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
    rel_off = o.runs(rv, 17)
    c = collections.Counter(); c2 = collections.Counter()
    for q in rel_off:
        if int(I[q + 4]) != 11: continue
        p, ch = int(I[q + 8]), int(I[q + 12])
        c[('parent_decoded' if p in byp else 'parent_missing', 'rel_prefix=%d' % data[q - 1])] += 1
        if ch in byp:
            c2[('parent_decoded' if p in byp else 'parent_missing', 'child_prefix=%d' % data[byp[ch]['off'] - 1])] += 1
    print('==', os.path.basename(f)[:16], eng)
    for k, v in sorted(c.items()): print('   relation', k, v)
    for k, v in sorted(c2.items()): print('   child part record', k, v)
    pc = collections.Counter(data[m['off'] - 1] for m in M)
    print('   all decoded part records prefix', pc.most_common(8))
