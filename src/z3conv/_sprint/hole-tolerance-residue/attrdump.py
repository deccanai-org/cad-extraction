"""attrdump.py DB1 : raw part_attr records (stride 373) of old-engine bolt groups (obj_type 10) -> varying int/float fields"""
import sys, re, gzip, collections, numpy as np
sys.path.insert(0, 'kit')
import db1old
data = open(sys.argv[1], 'rb').read()
if data[:2] == b'\x1f\x8b': data = gzip.decompress(data)
o = db1old.Old(data); N = len(o.I_all) - 400; I = o.I_all
av = np.zeros(N, bool); M = N - 380
av[:M] = (I[:M] > 0) & (I[4:M + 4] >= 0) & (I[4:M + 4] <= 100) & (I[72:M + 72] >= 0) & (I[72:M + 72] <= 64)
pr = o.u8[124:124 + M]; av[:M] &= (pr >= 32) & (pr <= 126)
at_off = o.runs(av, 373)
recs = [int(q) for q in at_off if int(I[q + 4]) == 10]
print('bolt attr records', len(recs))
rows = []
for q in recs:
    prof = o.cstr(q + 124, 62); mat = o.cstr(q + 270, 22)
    rows.append((q, prof, mat))
# which 4-byte aligned offsets vary among bolt records (outside the strings)?
skip = set(range(102, 124)) | set(range(124, 186)) | set(range(270, 292))
var = []
for k in range(0, 373 - 4):
    if any(x in skip for x in range(k, k + 4)): continue
    vals = collections.Counter(int(I[q + k]) for q, _, _ in rows)
    if len(vals) > 1: var.append((k, len(vals), vals.most_common(4)))
for k, n, mc in var[:80]: print(k, n, mc)
