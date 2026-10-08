"""Compare our member solids' axis-aligned bounding boxes with the IFC's, for IFC-matched members.

Tries orientation conventions and reports the median/p90 bbox corner error (inches) for each.
usage: python validate_bbox.py <job_dir> <ifc_axes.csv> <mem_ifc_pairs.csv> <shift_x_in> <shift_y_in>
"""
import sys, csv, itertools
import numpy as np
from sds2job import read_members
import to_step as T

job, axes, pairs_csv, sx, sy = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5])
IN = 0.0254
mems = {m.id: m for m in read_members(job)[0]}
ifc = {}
for r in csv.DictReader(open(axes)):
    lo = np.array([float(r["minx"]) / IN - sx, float(r["miny"]) / IN - sy, float(r["minz"]) / IN])
    hi = np.array([float(r["maxx"]) / IN - sx, float(r["maxy"]) / IN - sy, float(r["maxz"]) / IN])
    ifc.setdefault(r["piecemark"], []).append((lo, hi, r["type"]))
pairs = list(csv.DictReader(open(pairs_csv)))


def our_bbox(m, upv, tos, rollsign):
    m2 = type(m)(**{**m.__dict__, "roll": m.roll * rollsign})
    fr = T.frame(m2, upv)
    if fr is None or m.section is None: return None
    p1, x, u, v, L = fr
    loops = T.profile(m.section)
    off = -m.section.d / 2 if (tos and m.type in ("BEAM", "PL GIRDER") and abs(x[2]) < 0.999) else 0.0
    pts = [p1 + u * (a + off) + v * b + x * t for a, b in loops[0] for t in (0, L)]
    pts = np.array(pts)
    return pts.min(0), pts.max(0)


for upv, tos, rs in itertools.product(("X", "Y"), (1, 0), (1, -1)):
    errs = {"BEAM": [], "COLUMN": []}
    for p in pairs:
        m = mems.get(int(p["mem_id"]))
        if not m or m.type not in errs: continue
        bb = our_bbox(m, upv, tos, rs)
        if bb is None: continue
        best = min(ifc.get(p["piecemark"], []), key=lambda t: np.abs(t[0] - bb[0]).sum() + np.abs(t[1] - bb[1]).sum(), default=None)
        if best is None: continue
        # compare cross-section extents only (ends are cut back at connections): use the 2 axes perpendicular to member
        ax = np.argmax(np.abs(np.array(m.p2) - np.array(m.p1)))
        k = [i for i in range(3) if i != ax]
        e = np.abs(np.r_[best[0][k] - bb[0][k], best[1][k] - bb[1][k]]).max()
        errs[m.type].append(e)
    out = {t: (len(v), round(float(np.median(v)), 3), round(float(np.percentile(v, 90)), 3), round(float(np.mean(np.array(v) < 0.25)), 3)) for t, v in errs.items() if v}
    print(f"up_vertical={upv} beam_tos={tos} rollsign={rs}: (n, median, p90, share<0.25in) {out}")

