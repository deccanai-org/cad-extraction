"""Locate IFC member end-point coordinates inside mem/ records (vectorised).

Uses the 2D shift found by match_ifc.py (rotation ~0). Every (x,y,z) big-endian double triple in the first
MAXB bytes of every record, at alignments 0 and 2, goes into a KD-tree; IFC end points are queried against it.
usage: python find_offsets.py <job_dir> <ifc_axes.csv> <shift_x_in> <shift_y_in>
"""
import os, sys, csv, collections
import numpy as np
from scipy.spatial import cKDTree

job, axes, sx, sy = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
IN, MAXB = 0.0254, 4096
md = os.path.join(job, "mem")
pts, meta = [], []
for n in os.listdir(md):
    if not n.isdigit(): continue
    b = open(os.path.join(md, n), "rb").read()[:MAXB]
    for al in (0, 2, 4, 6):
        m = (len(b) - al) // 8
        if m < 3: continue
        v = np.frombuffer(b[al:al + 8 * m], dtype=">f8").astype(float)
        t = np.c_[v[:-2], v[1:-1], v[2:]]
        ok = np.isfinite(t).all(1) & (np.abs(t) < 1e6).all(1) & (np.abs(t).sum(1) > 1)
        idx = np.where(ok)[0]
        pts.append(t[idx]); meta.append(np.c_[np.full(len(idx), int(n)), al + 8 * idx])
P = np.concatenate(pts); M = np.concatenate(meta)
print("triples indexed:", len(P))
tree = cKDTree(P)

ifc = list(csv.DictReader(open(axes)))
Q, lab = [], []
for k, r in enumerate(ifc):
    for end in ("a", "b"):
        Q.append([float(r[end + "x"]) / IN - sx, float(r[end + "y"]) / IN - sy, float(r[end + "z"]) / IN]); lab.append((k, end))
Q = np.array(Q)
hits = tree.query_ball_point(Q, r=1.0)
hist = collections.Counter()
found = collections.defaultdict(set)
for (k, end), hs in zip(lab, hits):
    for h in hs:
        n, off = M[h]
        hist[off] += 1
        found[k].add((int(n), end, int(off)))
print("hit offsets (byte offset: count):", [(hex(o), c) for o, c in hist.most_common(20)])
both = sum(1 for k, s in found.items() if {e for _, e, _ in s} == {"a", "b"})
print(f"IFC members with any end found: {len(found)}/{len(ifc)}; both ends found: {both}")
ex = list(found.items())[:8]
for k, s in ex:
    print(" ", ifc[k]["piecemark"], ifc[k]["type"], sorted(s)[:6])
