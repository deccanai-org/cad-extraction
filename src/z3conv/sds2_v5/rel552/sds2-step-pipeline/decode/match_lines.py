"""Line-level match: mem work line (mem_idx slot P@0x112 -> P@0x172) vs IFC solid axis.

A mem record matches an IFC member when directions are parallel, the IFC axis midpoint lies within
LAT inches of the mem work line (top-of-steel vs centroid offset), and the IFC axis lies within the mem segment
(IFC length <= mem length + tol).
usage: python match_lines.py <job_dir> <ifc_axes.csv> <shift_x_in> <shift_y_in>
"""
import os, sys, struct, csv, collections
import numpy as np
from scipy.spatial import cKDTree

job, axes, sx, sy = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
IN, LAT = 0.0254, 30.0
md = os.path.join(job, "mem")
idx = open(os.path.join(md, "mem_idx"), "rb").read()
SLOT = 2494
ids, P1, P2, sizes = [], [], [], []
for n in os.listdir(md):
    if not n.isdigit(): continue
    b = open(os.path.join(md, n), "rb").read()
    if len(b) < 0xE8: continue
    s = idx[int(n) * SLOT:(int(n) + 1) * SLOT]
    ids.append(int(n)); P1.append(struct.unpack(">3d", s[0x112:0x12a])); P2.append(struct.unpack(">3d", s[0x172:0x18a])); sizes.append(len(b))
P1, P2 = np.array(P1), np.array(P2)
L = np.linalg.norm(P2 - P1, axis=1)
U = (P2 - P1) / np.where(L[:, None] > 0, L[:, None], 1)
mid = (P1 + P2) / 2
tree = cKDTree(mid)

ifc = list(csv.DictReader(open(axes)))
res = collections.Counter()
pairs = []
for r in ifc:
    a = np.array([float(r["ax"]) / IN - sx, float(r["ay"]) / IN - sy, float(r["az"]) / IN])
    b = np.array([float(r["bx"]) / IN - sx, float(r["by"]) / IN - sy, float(r["bz"]) / IN])
    li = np.linalg.norm(b - a); ui = (b - a) / li; mi = (a + b) / 2
    cand = tree.query_ball_point(mi, r=li / 2 + 200)
    best = None
    for c in cand:
        if L[c] < 1: continue
        if abs(U[c] @ ui) < 0.995: continue
        w = mi - P1[c]; t = w @ U[c]
        lat = np.linalg.norm(w - t * U[c])
        if lat > LAT or t < -12 or t > L[c] + 12: continue
        dl = L[c] - li
        if dl < -12 or dl > 60: continue
        sc = lat + abs(dl) * 0.2
        if best is None or sc < best[0]:
            best = (sc, c, lat, dl)
    if best:
        res[r["type"] + " matched"] += 1
        pairs.append((r["piecemark"], r["section"], ids[best[1]], round(best[2], 2), round(best[3], 2), sizes[best[1]]))
    else:
        res[r["type"] + " unmatched"] += 1
print(dict(res))
lat = np.array([p[3] for p in pairs]); dl = np.array([p[4] for p in pairs])
print("lateral offset (in) median/p90:", np.median(lat).round(2), np.percentile(lat, 90).round(2))
print("mem length - ifc length (in) median/p90:", np.median(dl).round(2), np.percentile(dl, 90).round(2))
print("distinct mem records used:", len({p[2] for p in pairs}))
print("samples:", pairs[:12])
with open(os.path.join(os.path.dirname(axes), "mem_ifc_pairs.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["piecemark", "section", "mem_id", "lateral_in", "dlen_in", "rec_size"]); w.writerows(pairs)

