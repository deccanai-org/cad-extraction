"""For relation types whose child is object-only: find the child's non-object records (raw) and show their field signature."""
import sys, os, re, json, collections, struct, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old
from db1dec import load
f = sys.argv[2]; want = [int(t) for t in sys.argv[3].split(',')]; which = sys.argv[4] if len(sys.argv) > 4 else 'id2'
data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng)
byp = {m['pid']: m for m in M}
o = db1old.Old(data); I, D, F = o.I_all, o.D_all, o.F_all; N = len(I) - 400
pos = [m.start() for m in re.finditer(rb'ID[0-9A-F]{8}-[0-9A-F]{4}-', data)]
objq = {p - 28 for p in pos if p > 28 and data[p - 29] == 4}
rv = np.zeros(N, bool); Mr = N - 20
rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
rel = o.runs(rv, 17); relq = set(int(q) for q in rel)
for t in want:
    ids = [(int(I[q + 8]), int(I[q + 12])) for q in rel if int(I[q + 4]) == t]
    print('== type', t, len(ids))
    sig = collections.Counter(); shown = 0
    for a, b in ids:
        tgt = b if which == 'id2' else a
        if tgt in byp: continue
        pat = struct.pack('<i', tgt); q = data.find(pat); recs = []
        while q >= 0:
            if q >= 1 and data[q - 1] == 4 and q not in objq and q not in relq:
                recs.append(q)
            q = data.find(pat, q + 1)
        # records where the id sits at offset 0 of a live record
        for q in recs:
            # find the stride: distance to the next live record with the same "shape" is unknown; print the first 12 ints + doubles
            ints = [int(I[q + 4 * k]) for k in range(12)]
            dbl = [round(float(D[q + 8 + 8 * k]), 3) for k in range(8)]
            key = tuple(1 if (isinstance(v, int) and 0 < v < 10_000_000) else 0 for v in ints[:8])
            sig[key] += 1
            if shown < 12:
                print('   ', t, 'parent', a, '-> child', b, '@', q, 'ints', ints, 'dbl', dbl)
                shown += 1
    print('   signatures', sig.most_common(5))
