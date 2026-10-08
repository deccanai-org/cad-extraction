"""Per member type (from mem_idx slot +0x988): counts, record sizes, P1/P2 geometry stats; nearest-miss diagnostics."""
import os, sys, struct, csv, collections, re
import numpy as np
from scipy.spatial import cKDTree

job, axes, sx, sy = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
IN, SLOT = 0.0254, 2494
md = os.path.join(job, "mem")
idx = open(os.path.join(md, "mem_idx"), "rb").read()
def mtype(n):
    s = idx[n * SLOT + 0x988: n * SLOT + 0x988 + 24]
    m = re.match(rb"[ -~]+", s)
    return m.group().decode() if m else "?"
rows = []
for n in os.listdir(md):
    if not n.isdigit(): continue
    b = open(os.path.join(md, n), "rb").read()
    if len(b) < 0xE8: continue
    d = struct.unpack(">29d", b[:0xE8])
    rows.append((int(n), mtype(int(n)), len(b), np.array(d[9:12]), np.array(d[26:29])))
by = collections.defaultdict(list)
for r in rows: by[r[1]].append(r)
for t, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
    L = np.array([np.linalg.norm(r[4] - r[3]) for r in rs])
    vert = np.mean([abs((r[4] - r[3])[2]) > 0.99 * np.linalg.norm(r[4] - r[3]) > 0 for r in rs])
    horiz = np.mean([abs((r[4] - r[3])[2]) < 0.01 * max(np.linalg.norm(r[4] - r[3]), 1e-9) and np.linalg.norm(r[4]-r[3]) > 0 for r in rs])
    print(f"{t:14s} n={len(rs):5d} sizes={collections.Counter(r[2] for r in rs).most_common(2)} len median={np.median(L):8.1f} zero-len={np.mean(L<1):.2f} vert={vert:.2f} horiz={horiz:.2f}")
# a few beam examples
for r in by.get("BEAM", [])[:5] + by.get("COLUMN", [])[:3]:
    print(r[0], r[1], r[2], r[3].round(2), r[4].round(2))
# IFC beams in job coords
ifc = list(csv.DictReader(open(axes)))
ib = [r for r in ifc if r["type"] == "IfcBeam"][:5]
for r in ib:
    print("IFC", r["piecemark"], r["section"], np.round([float(r["ax"]) / IN - sx, float(r["ay"]) / IN - sy, float(r["az"]) / IN], 2), np.round([float(r["bx"]) / IN - sx, float(r["by"]) / IN - sy, float(r["bz"]) / IN], 2))
