"""Test ownership hypotheses between members and subm pieces.

Reads member work lines/sections (sds2job) and subm_idx slot fields (section idx @0x110 i32, name @0x12E,
length @0x16C, depth @0x174, 0x204 = full length?). Prints for a few members and nearby subm ids.
"""
import os, sys, re, struct, collections
import numpy as np
from sds2job import read_members

job = sys.argv[1]
SS = 852
mems, L = read_members(job)
M = {m.id: m for m in mems}
sb = open(os.path.join(job, "subm", "subm_idx"), "rb").read()
def subm(n):
    s = sb[n * SS:(n + 1) * SS]
    nm = re.match(rb"[ -~]*", s[0x12E:0x12E + 30]).group().decode()
    sec = struct.unpack(">i", s[0x110:0x114])[0]
    ln, dp, full = (struct.unpack(">d", s[o:o + 8])[0] for o in (0x16C, 0x174, 0x204))
    return nm, sec, round(ln, 3), round(dp, 3), round(full, 3)
for n in (1, 2, 3, 62, 63, 1001, 1003, 5000):
    m = M.get(n)
    if m:
        ln = np.linalg.norm(np.array(m.p2) - np.array(m.p1))
        print(f"member {n}: {m.type} {m.section.name if m.section else None} worklen={ln:.3f}  | subm {n}: {subm(n)}")
# does ANY subm with same section and length≈worklen exist, and how are their ids related?
by = collections.defaultdict(list)
N = (len(sb) - 256) // SS
for k in range(1, N):
    nm, sec, ln, dp, full = subm(k)
    if nm: by[(nm, round(full, 1))].append(k)
for n in (62, 63, 64, 1001, 1003, 1004, 5000):
    m = M.get(n)
    if not m or not m.section: continue
    wl = round(float(np.linalg.norm(np.array(m.p2) - np.array(m.p1))), 1)
    cands = [k for (nm, fl), ks in by.items() if nm == m.section.name and abs(fl - wl) < 0.2 for k in ks]
    print(f"member {n} {m.section.name} wl={wl}: subm with same section & full length: {cands[:10]}")
