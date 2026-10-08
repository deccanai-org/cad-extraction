"""Shaded close-up of stage-2 pieces within a radius of a point (job inches), rebuilt from the same decoders.
usage: python preview2.py <job> <x,y,z> <radius> <out.png> [title]"""
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from instances import material_instances, subm_vertices
from piece_table import read_pieces, kind
from sds2job import read_shapes, read_members
from to_step2 import plate_local, rolled_local

job = sys.argv[1]; c = np.array([float(v) for v in sys.argv[2].split(",")]); R = float(sys.argv[3])
pieces = read_pieces(job); shapes = read_shapes(job); mems, _ = read_members(job)
faces, cols = [], []
colour = {"plate": "#dd8a3a", "rolled": "#4a78b5"}
for m in mems:
    if np.linalg.norm(np.array(m.p1) - c) > R + 800 and np.linalg.norm(np.array(m.p2) - c) > R + 800: continue
    for sid, M, o in material_instances(job, m.id, pieces)[1]:
        p = pieces[sid]; k = kind(p); V = subm_vertices(job, sid)
        if V is None or len(V) < 4: continue
        loc = plate_local(V, p) if k == "plate" else (rolled_local(V, shapes[p["sec"]], p["L"]) if p["sec"] in shapes else None)
        if not loc: continue
        loop, e = loc[0], loc[1]
        A = np.array([o + M.T @ q for q in loop]); B = A + M.T @ e
        # clip long members to the view sphere so the close-up stays readable
        if np.min(np.linalg.norm(np.r_[A, B] - c, axis=1)) > R: continue
        faces.append(A); faces.append(B); cols += [colour[k]] * 2
        for i in range(len(A)):
            j = (i + 1) % len(A); faces.append(np.array([A[i], A[j], B[j], B[i]])); cols.append(colour[k])
fig = plt.figure(figsize=(10, 9), dpi=110); ax = fig.add_subplot(projection="3d")
ax.add_collection3d(Poly3DCollection(faces, facecolors=cols, edgecolors="#222", linewidths=0.15, alpha=0.95))
ax.set_xlim(c[0] - R, c[0] + R); ax.set_ylim(c[1] - R, c[1] + R); ax.set_zlim(c[2] - R, c[2] + R)
ax.set_box_aspect((1, 1, 1)); ax.view_init(elev=25, azim=-55); ax.set_axis_off()
ax.set_title(sys.argv[5] if len(sys.argv) > 5 else "stage-2 pieces")
plt.tight_layout(); plt.savefig(sys.argv[4]); print("saved", sys.argv[4], len(faces), "faces")
