"""Survey instance-block candidates: every place in mem/<n> where i32 n appears at R+8 and R holds a subm id whose
subm file exists and whose preceding 72 bytes form a rotation matrix. Reports counts and which extra tags hold."""
import os, sys, struct, re, collections
import numpy as np

job = sys.argv[1]
md, sd = os.path.join(job, "mem"), os.path.join(job, "subm")
subm_ids = set(int(x) for x in os.listdir(sd) if x.isdigit())
np.seterr(all="ignore")
stats = collections.Counter(); per = collections.Counter(); r20 = collections.Counter(); gaps = collections.Counter()
for n in sorted(int(x) for x in os.listdir(md) if x.isdigit()):
    b = open(os.path.join(md, str(n)), "rb").read()
    tag = struct.pack(">i", n)
    found = []
    for m in re.finditer(re.escape(tag), b):
        R = m.start() - 8
        if R < 334: continue
        sid = struct.unpack(">i", b[R:R + 4])[0]
        if sid not in subm_ids: continue
        M = np.array(struct.unpack(">9d", b[R - 334:R - 262])).reshape(3, 3)
        if not np.isfinite(M).all() or abs(abs(np.linalg.det(M)) - 1) > 1e-3: stats["bad matrix"] += 1; continue
        found.append(R); r20[b[R + 20:R + 24] == tag] += 1
    per[min(len(found), 30)] += 1
    for i in range(len(found) - 1): gaps[found[i + 1] - found[i]] += 1
    stats["instances"] += len(found)
print(stats, "\nR+20 tag present:", r20, "\nper-member:", sorted(per.items()), "\nblock gaps:", gaps.most_common(10))
