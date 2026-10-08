"""Deep-dive one member: IFC connection parts in member-local coords vs the member's instance blocks.

usage: python one_member.py <job> <ifc_parts.csv> <mem_ifc_pairs.csv> <shift_x> <shift_y> <piecemark>
"""
import sys, csv, re, struct, os
import numpy as np
from sds2job import read_members
import to_step as T
from instances import material_instances, subm_vertices

job, parts_csv, pairs_csv, sx, sy, pm = sys.argv[1:7]
sx, sy = float(sx), float(sy)
IN = 0.0254
mid = next(int(r["mem_id"]) for r in csv.DictReader(open(pairs_csv)) if r["piecemark"] == pm)
mems, _ = read_members(job)
m = next(x for x in mems if x.id == mid)
p1, x, u, v, L = T.frame(m, "X")
F = np.c_[x, u, v]
print(f"{pm} -> mem {mid} {m.type} {m.section.name} p1={np.round(p1,2)} L={L:.2f}\n  x={np.round(x,3)} u={np.round(u,3)} v={np.round(v,3)}")
# IFC parts of this piecemark, in member-local coordinates (bbox)
sb = open(os.path.join(job, "subm", "subm_idx"), "rb").read()
def sname(sid):
    s = sb[sid * 852:(sid + 1) * 852]
    return re.match(rb"[ -~]*", s[0x12E:0x15E]).group().decode(), [round(struct.unpack(">d", s[o:o + 8])[0], 3) for o in (0x16C, 0x174, 0x17C)]
# parts CSV lacks member piecemark; use proximity: parts whose centroid lies within 30in of the member's segment
rows = []
for r in csv.DictReader(open(parts_csv)):
    c = np.array([float(r["cx"]) / IN - sx, float(r["cy"]) / IN - sy, float(r["cz"]) / IN])
    loc = F.T @ (c - p1)
    if -30 < loc[0] < L + 30 and np.hypot(loc[1], loc[2]) < 30:
        lo = F.T @ (np.array([float(r["minx"]), float(r["miny"]), float(r["minz"])]) / IN - [sx, sy, 0] - p1)
        hi = F.T @ (np.array([float(r["maxx"]), float(r["maxy"]), float(r["maxz"])]) / IN - [sx, sy, 0] - p1)
        rows.append((r["mat_piecemark"], r["desc"], np.round(loc, 2), np.round(np.abs(hi - lo), 2)))
print(f"IFC parts near member (local centroid, |extent|): {len(rows)}")
for r in sorted(rows, key=lambda r: r[2][0])[:25]: print("  ", r)
main, inst = material_instances(job, mid)
print(f"main material subm {main}: {sname(main)}; material blocks: {len(inst)}")
for sid, M, o in inst:
    print(f"  subm {sid} {sname(sid)} origin(local)={np.round(F.T @ (o - p1), 2)} M={np.round(M, 3).tolist()}")
