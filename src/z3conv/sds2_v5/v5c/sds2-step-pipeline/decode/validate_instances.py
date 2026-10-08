"""Place material instances in world coords from the piece table (plates = L x W x T box, rolled = bbox of
section x length) and compare with IFC connection parts: precision (ours near an IFC part) and recall
(IFC parts near one of ours). Local piece bbox convention: x in [0,L], y in [-W,0], z in [0,T or bf].
usage: python validate_instances.py <job> <ifc_parts.csv> <shift_x_in> <shift_y_in>
"""
import os, sys, csv, collections
import numpy as np
from scipy.spatial import cKDTree
from instances import material_instances, subm_vertices
from piece_table import read_pieces, kind
from sds2job import read_shapes

job, parts_csv, sx, sy = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
IN = 0.0254
rows = list(csv.DictReader(open(parts_csv)))
P = np.array([[float(r["cx"]) / IN - sx, float(r["cy"]) / IN - sy, float(r["cz"]) / IN] for r in rows])
tree = cKDTree(P)
pieces = read_pieces(job); shapes = read_shapes(job)
ours, kinds = [], []
per = collections.Counter(); nov = collections.Counter()
for n in sorted(int(x) for x in os.listdir(os.path.join(job, "mem")) if x.isdigit()):
    main, inst = material_instances(job, n, pieces)
    per[min(len(inst), 20)] += 1
    for sid, M, o in inst:
        p = pieces[sid]
        V = subm_vertices(job, sid)
        if V is None or len(V) < 4:
            nov[kind(p)] += 1; continue
        c = (V.min(0) + V.max(0)) / 2
        ours.append(o + M.T @ c); kinds.append(kind(p))
ours = np.array(ours)
d, _ = tree.query(ours)
print("members by #instances:", sorted(per.items()), "; instances without vertices:", dict(nov))
print(f"our instances: {len(ours)}  precision (<1in / <3in of an IFC part): {np.mean(d<1):.3f} / {np.mean(d<3):.3f}")
for k in ("plate", "rolled"):
    dk = d[np.array(kinds) == k]
    if len(dk): print(f"   {k}: n={len(dk)} <1in {np.mean(dk<1):.3f} <3in {np.mean(dk<3):.3f} median {np.median(dk):.2f}")
d2, _ = cKDTree(ours).query(P)
kind_ifc = np.array(["plate" if r["desc"] == "Plate" else "rolled" for r in rows])
print(f"IFC parts: {len(P)}  recall (<1in / <3in): {np.mean(d2<1):.3f} / {np.mean(d2<3):.3f}")
for k in ("plate", "rolled"):
    dk = d2[kind_ifc == k]
    print(f"   {k}: n={len(dk)} <1in {np.mean(dk<1):.3f} <3in {np.mean(dk<3):.3f}")


