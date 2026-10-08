"""Find every (piece id, member id) pair in mem/<n>: i32 at X in piece table, i32 at X+4 == n.
Check whether a rotation matrix sits at X-0x60 and a sane origin at X-0x18 (the 538-B block pattern);
report counts by piece kind, where they sit, and spacing between consecutive refs."""
import os, sys, struct, re, collections
import numpy as np
from piece_table import read_pieces, kind

job = sys.argv[1]
P = read_pieces(job)
md = os.path.join(job, "mem")
np.seterr(all="ignore")
cnt = collections.Counter(); gaps = collections.Counter(); first = collections.Counter(); byfile = collections.Counter()
for n in sorted(int(x) for x in os.listdir(md) if x.isdigit()):
    b = open(os.path.join(md, str(n)), "rb").read()
    tag = struct.pack(">i", n)
    xs = []
    for m in re.finditer(re.escape(tag), b):
        X = m.start() - 4
        if X < 0x60: continue
        sid = struct.unpack(">i", b[X:X + 4])[0]
        p = P.get(sid)
        if not p: continue
        M = np.array(struct.unpack(">9d", b[X - 0x60:X - 0x18])).reshape(3, 3)
        o = np.array(struct.unpack(">3d", b[X - 0x18:X]))
        good = np.isfinite(M).all() and abs(abs(np.linalg.det(M)) - 1) < 1e-3 and np.isfinite(o).all() and np.abs(o).max() < 1e6
        cnt[(kind(p), good)] += 1
        if good: xs.append(X)
    for i in range(len(xs) - 1): gaps[xs[i + 1] - xs[i]] += 1
    if xs: first[xs[0]] += 1
print("refs (kind, has matrix+origin):", dict(cnt))
print("spacing between good refs:", gaps.most_common(10))
print("first good ref offset:", first.most_common(6))
