"""slotscan.py DB1... : old-engine bolt-group attribute records (part_attr, stride 373): int32 / byte fields that separate slotted groups
(slot x or y != 0 in the bolt string) from non-slotted ones -> candidates for the 'slotted holes in parts' mask"""
import sys, re, gzip, collections, numpy as np
sys.path.insert(0, 'kit_i')
import db1old
tot_s = collections.defaultdict(collections.Counter); tot_n = collections.defaultdict(collections.Counter); ns = nn = 0
for f in sys.argv[1:]:
    data = open(f, 'rb').read()
    if data[:2] == b'\x1f\x8b': data = gzip.decompress(data)
    o = db1old.Old(data); N = len(o.I_all) - 400; I = o.I_all
    av = np.zeros(N, bool); M = N - 380
    av[:M] = (I[:M] > 0) & (I[4:M + 4] >= 0) & (I[4:M + 4] <= 100) & (I[72:M + 72] >= 0) & (I[72:M + 72] <= 64)
    pr = o.u8[124:124 + M]; av[:M] &= (pr >= 32) & (pr <= 126)
    at = o.runs(av, 373)
    for q in at:
        q = int(q)
        if int(I[q + 4]) != 10: continue
        p = o.cstr(q + 124, 62).split('/')
        try: sl = float(p[1]) != 0 or float(p[2]) != 0
        except Exception: continue
        T = tot_s if sl else tot_n
        if sl: ns += 1
        else: nn += 1
        for k in list(range(8, 102, 4)) + list(range(186, 270, 4)) + list(range(292, 369, 4)):
            T[k][int(I[q + k])] += 1
print('slotted groups', ns, 'non-slotted', nn)
for k in sorted(tot_s):
    a, b = tot_s[k], tot_n[k]
    if len(a) + len(b) <= 2 and set(a) == set(b): continue
    za = a.get(0, 0) / max(1, sum(a.values())); zb = b.get(0, 0) / max(1, sum(b.values()))
    if abs(za - zb) > 0.2 or (len(a) > 1 and all(0 <= v < 64 for v in a) and set(a) != set(b)):
        print(k, 'slotted', a.most_common(6), '| non-slotted', b.most_common(6))
