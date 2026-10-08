"""Read-only: show one piece's local vertex extents, outliers, and the instances placing it on a member."""
import sys
import numpy as np
from instances import material_instances, subm_vertices
from piece_table import read_pieces
from sds2job import read_shapes

job, mid, sid = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
pieces = read_pieces(job); shapes = read_shapes(job)
p = pieces[sid]; sh = shapes.get(p["sec"])
V = subm_vertices(job, sid)
print(p, "section", sh.name if sh else None, "d/bf", (sh.d, sh.bf) if sh else None)
print("vertices", len(V), "local min", V.min(0).round(2), "max", V.max(0).round(2))
for ax in range(3):
    q = np.percentile(V[:, ax], [0, 1, 5, 50, 95, 99, 100]).round(2)
    print(f"  axis {ax} percentiles 0/1/5/50/95/99/100:", q)
far = V[(np.abs(V[:, 1] - np.median(V[:, 1])) > 30) | (np.abs(V[:, 2] - np.median(V[:, 2])) > 30)]
print("far vertices:", len(far), far[:8].round(2).tolist())
for s, M, o in material_instances(job, mid, pieces)[1]:
    if s == sid:
        print("instance origin", o.round(2), "M", M.round(3).tolist())
