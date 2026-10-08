"""Representative open-web steel joist (stand-in) for joist members that SDS2 stores without chord / web data.

Pre-2018 SDS2 jobs (7.0-7.6) hold a joist as a member with a designation only (24K6, 32LH10, 64DLH12): its job_mtrl
record carries the depth, a 6-in envelope width, seat depths and a series placeholder weight (2.5 lb/ft for K,
5 lb/ft for LH / DLH on Greenwood 7.312), no chord or web sizes, and the member has no fabricated pieces. v4 wrote
such joists as solid d x 6 in boxes (Greenwood: 205 joists at 100-260x SDS2's weight per foot, FIX item 1).

v5 writes an open-web joist instead: top and bottom chords as back-to-back angle pairs and a zig-zag web of round
bars between them, the depth from the designation (= the record depth), the top of the top chord on the work line
(as the stage-1 envelope), and the mass of a typical joist of that designation (SJI K-series typical weights; LH /
DLH from a depth / size-number estimate). It is a tagged stand-in, not the fabricated joist: every such solid is
named "... [stand-in: open-web joist ...]" and listed in the job's manifest with its mass basis.
"""
import math, re
import numpy as np

MM = 25.4
STEEL = 0.2836      # lb / in3

# SJI K-series typical weight (lb/ft) by designation (standard load table values, rounded)
SJI_K = {
    "8K1": 5.1, "10K1": 5.0, "12K1": 5.0, "12K3": 5.7, "12K5": 7.1, "14K1": 5.2, "14K3": 6.0, "14K4": 6.7,
    "14K6": 7.7, "16K2": 5.5, "16K3": 6.3, "16K4": 7.0, "16K5": 7.5, "16K6": 8.1, "16K7": 8.6, "16K9": 10.0,
    "18K3": 6.6, "18K4": 7.2, "18K5": 7.7, "18K6": 8.5, "18K7": 9.0, "18K9": 10.2, "18K10": 11.7, "20K3": 6.7,
    "20K4": 7.6, "20K5": 8.2, "20K6": 8.9, "20K7": 9.3, "20K9": 10.8, "20K10": 12.2, "22K4": 8.0, "22K5": 8.8,
    "22K6": 9.2, "22K7": 9.7, "22K9": 11.3, "22K10": 12.6, "22K11": 13.8, "24K4": 8.4, "24K5": 9.3, "24K6": 9.7,
    "24K7": 10.1, "24K8": 11.5, "24K9": 12.0, "24K10": 13.1, "24K12": 16.0, "26K5": 9.8, "26K6": 10.6,
    "26K7": 10.9, "26K8": 12.1, "26K9": 12.2, "26K10": 13.8, "26K12": 16.6, "28K6": 11.4, "28K7": 11.8,
    "28K8": 12.7, "28K9": 13.0, "28K10": 14.3, "28K12": 17.1, "30K7": 12.3, "30K8": 13.2, "30K9": 13.4,
    "30K10": 15.0, "30K11": 16.4, "30K12": 17.6,
}
# SJI series K / KCS / LH / DLH / SLH, deep super long span DSLH, composite CJ, joist girders G / BG / VG / JG.
# v5.2-v5.4.1 lacked DSLH: 50 JOIST 52DSLH / 64DSLH members of data-3 19002-IMS6 (7.720, joist records d = 0) lost
# their depth and silently wrote no solid (v5.1 drew them).
DESIG = re.compile(r"^(\d+(?:\.\d+)?)\s*(KCS|DSLH|SLH|DLH|LH|CJ|K|BG|VG|JG|G)(\d+)?", re.I)


def is_joist_section(name):
    return bool(DESIG.match(name or ""))


def typical_weight(name, depth, sds2_wt):
    """-> (lb/ft, basis). SDS2's record weight is used only when it is not the series placeholder (2.5 / 5.0)."""
    key = (name or "").upper().split("/")[0].strip()
    if key in SJI_K:
        return SJI_K[key], "SJI K-series typical weight for the designation"
    m = DESIG.match(key)
    if sds2_wt and sds2_wt > 0 and sds2_wt not in (2.5, 5.0):
        return float(sds2_wt), "SDS2 job_mtrl weight per foot"
    d = float(m.group(1)) if m else depth
    size = int(m.group(3)) if m and m.group(3) else 6
    series = m.group(2).upper() if m else "K"
    if series == "K" or series == "KCS":
        return round(3.0 + 0.16 * d + 0.55 * size, 1), "K-series estimate from depth and size number"
    if series in ("LH", "SLH"):
        return round(4.0 + 0.25 * d + 1.1 * size, 1), "LH-series estimate from depth and size number"
    if series in ("DLH", "DSLH"):
        return round(6.0 + 0.30 * d + 1.4 * size, 1), "DLH-series estimate from depth and size number"
    return round(max(5.0, 0.4 * d), 1), "joist girder estimate from depth"


def _angle(x0, L, u0, v0, b, t, su, sv):
    """Angle prism along +x: heel at (u0, v0), legs b along su*u and sv*v, thickness t (local x/u/v = X/Y/Z)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Pnt, gp_Vec
    pts = [(u0 + su * a, v0 + sv * c) for a, c in ((0, 0), (b, 0), (b, t), (t, t), (t, b), (0, b))]
    area2 = sum(pts[k][0] * pts[k - 1][1] - pts[k - 1][0] * pts[k][1] for k in range(len(pts)))
    if area2 > 0:
        pts = pts[::-1]                                         # face normal along +x -> positive prism volume
    poly = BRepBuilderAPI_MakePolygon()
    for a, c in pts:
        poly.Add(gp_Pnt(x0 * MM, a * MM, c * MM))
    poly.Close()
    f = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
    return BRepPrimAPI_MakePrism(f, gp_Vec(L * MM, 0, 0)).Shape()


def _bar(p, q, r):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir
    d = np.asarray(q, float) - np.asarray(p, float); L = float(np.linalg.norm(d))
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*(np.asarray(p) * MM)), gp_Dir(*(d / L))), r * MM, L * MM).Shape()


def joist_local(depth, length, wt):
    """Local joist along +x from 0 to length; local Y = up (top of top chord at y = 0, bottom of bottom chord at
    y = -depth), local Z = across. Returns (compound, info)."""
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRep import BRep_Builder
    depth = max(float(depth), 6.0)
    b = min(max(1.25 + depth / 32.0, 1.25), 5.0)               # chord angle leg
    gap = 1.0 if depth < 40 else 1.5                            # web bars sit between the back-to-back angles
    A_tot = wt / (12 * STEEL)                                   # in2 of steel per in of joist
    A_ang = 0.375 * A_tot / 2                                   # 75 % chords: 2 chords x 2 angles
    t = (2 * b - math.sqrt(max(4 * b * b - 4 * A_ang, 0))) / 2  # t (2b - t) = A_ang
    t = min(max(t, 0.1), b / 3)
    parts = []
    for top in (True, False):
        u0 = 0.0 if top else -depth
        su = -1 if top else 1                                   # vertical legs point into the joist
        for side in (-1, 1):
            parts.append(_angle(0.0, length, u0, side * gap / 2, b, t, su, side))
    # web: zig-zag between the chord centroid lines, ~45 degree diagonals
    yc_top, yc_bot = -b * 0.3, -depth + b * 0.3
    h = yc_top - yc_bot
    n = max(2, int(round(length / max(min(h, 60.0), 12.0))))
    s = length / n
    total = n * math.hypot(s, h)
    A_web = 0.25 * A_tot * length / total
    r = min(max(math.sqrt(A_web / math.pi), 0.2), gap / 2 + 0.25)
    for k in range(n):
        x0, x1 = k * s, (k + 1) * s
        y0, y1 = (yc_top, yc_bot) if k % 2 == 0 else (yc_bot, yc_top)
        parts.append(_bar((x0, y0, 0.0), (x1, y1, 0.0), r))
    c = TopoDS_Compound(); bb = BRep_Builder(); bb.MakeCompound(c)
    for p in parts:
        bb.Add(c, p)
    return c, dict(chord_angle=f"2L{b:.2f}x{b:.2f}x{t:.3f}", web_bar_dia=round(2 * r, 3), panels=n)


def joist_placed(m, wt):
    """(local compound, gp_Trsf world placement, info) for a joist member, or (None, None, None). v5.5.9: the stand-in is
    written as a local part plus a placement, like exact pieces. Built directly in world coordinates, its web-bar
    cylinders lost precision far from the origin and read back invalid (data-3 7.516: 140 bars of 67 joists ~62,000 in
    from the origin; the same joists placed as parts read back valid)."""
    import to_step as T
    from OCP.gp import gp_Trsf
    if m.section is None:
        return None, None, None
    fr = T.frame(m, "X")
    if fr is None:
        return None, None, None
    p1, x, u, v, L = fr
    depth = m.section.d
    dm = DESIG.match(m.section.name or "")
    if dm and (not depth or depth <= 0 or abs(depth - float(dm.group(1))) > 0.25 * float(dm.group(1))):
        depth = float(dm.group(1))
    if not depth or depth <= 0:
        return None, None, None
    try:
        local, info = joist_local(depth, L, wt)
        tr = gp_Trsf()
        R = np.c_[x, u, v]
        tr.SetValues(*R[0], p1[0] * MM, *R[1], p1[1] * MM, *R[2], p1[2] * MM)
        return local, tr, info
    except Exception:
        return None, None, None


def joist_solid(m, wt):
    """World-placed stand-in for a joist member (sds2job.Member), in mm, or (None, None). Same frame as the stage-1
    envelope (to_step.frame: x along the work line, u = up, v across, roll applied)."""
    import to_step as T
    from OCP.gp import gp_Trsf
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    if m.section is None:
        return None, None
    fr = T.frame(m, "X")
    if fr is None:
        return None, None
    p1, x, u, v, L = fr
    depth = m.section.d
    dm = DESIG.match(m.section.name or "")
    if dm and (not depth or depth <= 0 or abs(depth - float(dm.group(1))) > 0.25 * float(dm.group(1))):
        depth = float(dm.group(1))          # 7.6 boost records can carry d = 0 for joists: use the designation's depth
    if not depth or depth <= 0:
        return None, None
    try:
        local, info = joist_local(depth, L, wt)
        tr = gp_Trsf()
        R = np.c_[x, u, v]                                      # local X -> x, Y -> u, Z -> v
        tr.SetValues(*R[0], p1[0] * MM, *R[1], p1[1] * MM, *R[2], p1[2] * MM)
        return BRepBuilderAPI_Transform(local, tr, True).Shape(), info
    except Exception:
        return None, None
