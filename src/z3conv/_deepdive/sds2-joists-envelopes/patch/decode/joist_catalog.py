"""Open-web steel joist for SDS/2 joist members that carry only a designation (SDS/2 7.0-7.6 jobs).

What the job holds (verified on WLCSC 7.331, BAHAMAR 7.135, NY Bridge 7.425, Franklin Park 7.516):
  - member: work points (= top of top chord at the bearings; joist ends sit exactly the seat depth above the
    supporting beam's top of steel), roll, section index; member file = placement only (116 / 136 B), no material.
  - job_mtrl joist record (table "SDS2 Pre 7.0 USA", type code 7): d = nominal depth; bf = tf = tw = 6.0
    (placeholders); k = 0.375; the field sds2job decodes as `weight` is the SEAT DEPTH (2.5 K, 5.0 LH/DLH);
    further fields: d again, bearing gage (3.25 K / 4.0 LH-DLH), 6.0, 4.275, 4 x gage, one depth-only value,
    seat depth again.  Records of one depth are byte-identical across size numbers (16K2 = 16K3 = 16K4): there is
    NO chord, web or weight information for the designation anywhere in the job.
So the joist itself has to be derived.  Sources, most specific first:
  1. job:     depth, seat depth, span, slope, roll, position;
  2. catalog: SDS/2's BIMJoist material file shipped in the corpus job folders (plugins/BIMJoist/joists.xml,
              "Vulcraft 2003", 346 designations; joist_catalog.json): chord angle legs per designation, gap between
              the back-to-back angles (filler), seat angle, seat depth, bearing length, bottom-chord setback;
  3. SJI:     standard load table "approximate weight" (lb/ft) per designation -> chord thickness / web bar size so
              the joist mass is the published typical mass (the catalog's 1/4 in angles alone exceed it for K joists);
  4. layout:  SDS/2 JoistMtrl macro (B. Vaughan, macro folders of the corpus jobs): web working points 0.5 in inside
              the chords (rise = depth - 1), panels = int(run / (2 rise)), round-bar diagonals, first diagonal 6 in from
              the end, bottom chord 4 in past its end panel points.
Every such joist is a tagged stand-in: STEP name "... [approx: open-web joist <designation> derived ...]",
pieces-csv builder "joist_openweb_catalog".

Local frame (as piece files and the member's main-material placement, validated 578/578 on LINE 62 DOCKS 7.708 and
WLCSC 7.331: main material rotation rows = (x, u, v) of to_step.frame, origin = member p1): x along the work line
from p1 (0) to p2 (L), y = u (up, top of top chord at y = 0), z = v (across).
"""
import json, math, os, re
import numpy as np

MM = 25.4
LB_FT_PER_IN2 = 12 * 0.2836          # 3.4032 lb/ft per in2 of steel
HERE = os.path.dirname(os.path.abspath(__file__))
DESIG = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(KCS|K|LH|DLH|SLH)\s*[- ]?\s*(\d+)?\s*(.*?)\s*$", re.I)
ROLLED = re.compile(r"^(W|M|S|HP|HSS|TS|TB|C|MC|L|WT|MT|ST|PIPE|PLG|WBX|WPS|PL|FL|BAR|RD|SQ)\d", re.I)

# SJI standard load tables, "approximate weight (lbs/ft)" - K series (same values as sds2_v5 joist.py)
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
# SJI LH / DLH series approximate weights (lbs/ft), transcribed from the SJI LH/DLH standard load tables (+-1 lb/ft;
# consistent with the catalog chords: 24LH08 2L2.5x2.5x1/4 + 2L2.5x2.5x1/4 = 16.4 lb/ft of chords for 18 lb/ft)
SJI_LH = {
    "18LH02": 10, "18LH03": 11, "18LH04": 12, "18LH05": 15, "18LH06": 15, "18LH07": 17, "18LH08": 19, "18LH09": 21,
    "20LH02": 10, "20LH03": 11, "20LH04": 12, "20LH05": 14, "20LH06": 15, "20LH07": 17, "20LH08": 19, "20LH09": 21,
    "20LH10": 23, "24LH03": 11, "24LH04": 12, "24LH05": 13, "24LH06": 16, "24LH07": 17, "24LH08": 18, "24LH09": 21,
    "24LH10": 23, "24LH11": 25, "28LH05": 13, "28LH06": 16, "28LH07": 17, "28LH08": 18, "28LH09": 21, "28LH10": 23,
    "28LH11": 25, "28LH12": 27, "28LH13": 30, "32LH06": 14, "32LH07": 16, "32LH08": 17, "32LH09": 21, "32LH10": 21,
    "32LH11": 24, "32LH12": 27, "32LH13": 30, "32LH14": 33, "32LH15": 35, "36LH07": 16, "36LH08": 18, "36LH09": 21,
    "36LH10": 21, "36LH11": 23, "36LH12": 25, "36LH13": 30, "36LH14": 36, "36LH15": 36, "40LH08": 16, "40LH09": 21,
    "40LH10": 21, "40LH11": 22, "40LH12": 25, "40LH13": 30, "40LH14": 35, "40LH15": 36, "40LH16": 42, "44LH09": 19,
    "44LH10": 21, "44LH11": 22, "44LH12": 25, "44LH13": 30, "44LH14": 31, "44LH15": 36, "44LH16": 42, "44LH17": 47,
    "48LH10": 21, "48LH11": 22, "48LH12": 25, "48LH13": 29, "48LH14": 32, "48LH15": 36, "48LH16": 42, "48LH17": 47,
    "52DLH10": 25, "52DLH11": 26, "52DLH12": 29, "52DLH13": 34, "52DLH14": 39, "52DLH15": 42, "52DLH16": 45,
    "52DLH17": 52, "56DLH11": 26, "56DLH12": 30, "56DLH13": 34, "56DLH14": 39, "56DLH15": 42, "56DLH16": 46,
    "56DLH17": 51, "60DLH12": 29, "60DLH13": 35, "60DLH14": 40, "60DLH15": 43, "60DLH16": 46, "60DLH17": 52,
    "60DLH18": 59, "64DLH12": 31, "64DLH13": 34, "64DLH14": 40, "64DLH15": 43, "64DLH16": 46, "64DLH17": 52,
    "64DLH18": 59, "68DLH13": 37, "68DLH14": 40, "68DLH15": 40, "68DLH16": 49, "68DLH17": 55, "68DLH18": 61,
    "68DLH19": 67, "72DLH14": 41, "72DLH15": 44, "72DLH16": 50, "72DLH17": 56, "72DLH18": 59, "72DLH19": 70,
}
SJI = dict(SJI_K, **{k: float(v) for k, v in SJI_LH.items()})
CHORD_T = "catalog"          # "catalog" (SDS/2's own chord angles) | "sji" (thin the chords to the SJI typical mass)
_CAT = None


def catalog():
    global _CAT
    if _CAT is None:
        try:
            _CAT = json.load(open(os.path.join(HERE, "joist_catalog.json")))["joists"]
        except (OSError, ValueError, KeyError):
            _CAT = {}
    return _CAT


def parse(name):
    """'24K8' -> (24.0, 'K', 8, ''); '60DLH13SP2' -> (60.0, 'DLH', 13, 'SP2'); '18K-SP' -> (18.0, 'K', None, 'SP')"""
    m = DESIG.match(name or "")
    if not m:
        return None
    return float(m.group(1)), m.group(2).upper(), (int(m.group(3)) if m.group(3) else None), m.group(4).upper()


def is_joist_designation(name):
    """Open-web joist designation (K, KCS, LH, DLH, SLH), never a rolled / plate section name."""
    return bool(name) and not ROLLED.match(name) and parse(name) is not None


def is_joist_member(m):
    """Member written as an open-web joist when it has no pieces: its SECTION is a joist designation. The member type
    is not used: 7.0/7.1 jobs read with the v4 type offset label joists BEAM / COLUMN / MISC (BAHAMAR: 76 such), and
    Revit-imported jobs type W-shape framing JOIST (bghjk: 1,304 W/HSS/L/MC/WT members typed JOIST)."""
    s = getattr(m, "section", None)
    return s is not None and is_joist_designation(s.name) and (s.d > 0 or (parse(s.name) or (0,))[0] > 0)


def _norm(name):
    return re.sub(r"\s+", "", (name or "").upper())


def _chord_plf(tc, bc):
    a = lambda g: g[2] * (g[0] + g[1] - g[2])            # angle area, legs g[0], g[1], thickness g[2]
    return 2 * (a(tc) + a(bc)) * LB_FT_PER_IN2


def _nearest(series, depth, size):
    """catalog entry of the same series with chords: nearest depth, then nearest size number (no size number, e.g. a
    special 18K-SP: the median size at that depth)."""
    cands = []
    for k, v in catalog().items():
        p = parse(k)
        if p and p[1] == series and p[2] is not None and v.get("tc") and v.get("bc"):
            cands.append((abs(p[0] - depth), p[2], k, v))
    if not cands:
        return None
    dmin = min(c[0] for c in cands)
    same = sorted((c for c in cands if c[0] == dmin), key=lambda c: c[1])
    if size is None:
        c = same[len(same) // 2]
    else:
        c = min(same, key=lambda c: (abs(c[1] - size), c[1]))
    return (None, c[2], c[3])


def typical_weight(name, depth):
    """-> (lb/ft, basis)"""
    key = _norm(name)
    if key in SJI:
        return SJI[key], "SJI typical weight"
    p = parse(name)
    if not p:
        return max(5.0, 0.4 * depth), "estimate from depth"
    d, series, size, suffix = p
    base = f"{int(d) if d == int(d) else d}{series}{size:02d}" if size is not None and series in ("LH", "DLH", "SLH") else \
        (f"{int(d) if d == int(d) else d}{series}{size}" if size is not None else None)
    if base and base in SJI:
        return SJI[base], f"SJI typical weight of {base} (designation {name}: suffix {suffix or '-'})"
    same = sorted((pk[2], v, k) for k, v in SJI.items() if (pk := parse(k)) and pk[1] == ("LH" if series == "SLH" else series) and pk[0] == d)
    if same and size is not None:
        sz, v, k = min(same, key=lambda s: (abs(s[0] - size), s[0]))
        return v, f"SJI typical weight of {k}, the nearest standard size to {name}"
    if same:
        sz, v, k = same[len(same) // 2]
        return v, f"SJI weight of {k}, the median {int(d)}{series} size (special designation {name})"
    s = size if size is not None else 8
    if series in ("K", "KCS"):
        return round(3.0 + 0.16 * d + 0.55 * s, 1), "K-series estimate from depth and size number"
    if series in ("LH", "SLH"):
        return round(4.0 + 0.25 * d + 1.1 * s, 1), "LH-series estimate from depth and size number"
    return round(6.0 + 0.30 * d + 1.4 * s, 1), "DLH-series estimate from depth and size number"


def spec_for(name, depth, seat_from_job=None):
    """Joist dimensions for a designation -> dict (inches, lb/ft) with the source of every value."""
    p = parse(name)
    if p is None:
        return None
    dnom, series, size, suffix = p
    d = float(depth) if depth and depth > 0 else dnom
    cat = catalog()
    src = {}
    e = cat.get(_norm(name))
    if e is None and size is not None:                    # 60DLH13SP2 -> 60DLH13, 18LH2 -> 18LH02
        for k in (f"{int(dnom)}{series}{size}", f"{int(dnom)}{series}{size:02d}"):
            if k in cat:
                e = cat[k]; src["catalog_entry"] = k; break
    elif e is not None:
        src["catalog_entry"] = _norm(name)
    tc = bc = None
    if e and e.get("tc") and e.get("bc"):
        tc, bc = list(e["tc"]), list(e["bc"]); src["chords"] = f"catalog {src.get('catalog_entry')} (BIMJoist/Vulcraft 2003)"
    else:
        nb = _nearest("LH" if series == "SLH" else series, dnom, size)
        if nb and (abs(parse(nb[1])[0] - dnom) <= 4 or series in ("K", "KCS")):
            tc, bc = list(nb[2]["tc"]), list(nb[2]["bc"]); src["chords"] = f"catalog nearest {nb[1]} (no chords listed for {name})"
    gen = cat.get(f"{int(dnom)}{series}") or {}           # series default record (seat data for every depth)
    seat = list((e or {}).get("seat") or gen.get("seat") or ([2.0, 2.0, 0.25] if series in ("K", "KCS") else [4.0, 4.0, 0.25]))
    bl = (e or {}).get("bearing_length") or gen.get("bearing_length") or (4.0 if series in ("K", "KCS") else 6.0)
    filler = (e or {}).get("filler") or gen.get("filler") or (0.5 if series in ("K", "KCS") else 1.0)
    sb = (e or {}).get("bc_setback") or 0.0
    if not sb:
        sb = round(1.6 * d, 1); src["bc_setback"] = "1.6 x depth (no catalog setback)"
    else:
        src["bc_setback"] = "catalog"
    sd_cat = (e or {}).get("seat_depth") or gen.get("seat_depth")
    if seat_from_job in (2.5, 5.0, 7.5):
        sd = float(seat_from_job); src["seat_depth"] = "job_mtrl joist record"
    else:
        sd = float(sd_cat or (2.5 if series in ("K", "KCS") else 5.0)); src["seat_depth"] = "catalog" if sd_cat else "series default"
    W, wbasis = typical_weight(name, d)
    src["weight"] = wbasis
    if tc is None:                                        # DLH / SLH / 44-48LH: no chords in the catalog -> from weight
        A = 0.75 * W / LB_FT_PER_IN2 / 4                  # in2 per chord angle
        b = min(max(math.sqrt(5 * A), 2.0), 8.0); b = round(b * 4) / 4
        t = min(max(A / (2 * b), 0.25), b / 6); t = round(t * 16) / 16
        tc, bc = [b, b, t], [b, b, t]; src["chords"] = f"sized from {W:g} lb/ft (no catalog chords)"
    # chord thickness: CHORD_T = "catalog" keeps the catalog angles exactly, as SDS/2 itself draws joist chords (7.720
    # MORROW HS joist pieces: chord t = 1/4 in on 63/63, top-chord legs = catalog on 60/63); "sji" thins them so the
    # chords are 75 % of the SJI typical mass (K joists: catalog chords alone are 1.2-1.5x the SJI weight)
    tmin = 0.109 if series in ("K", "KCS") else 0.1875
    cp = _chord_plf(tc, bc)
    if CHORD_T == "sji" and cp > 0.85 * W:
        lo, hi = 0.05, 1.0
        for _ in range(40):
            k = (lo + hi) / 2
            cp_k = _chord_plf([tc[0], tc[1], max(tc[2] * k, tmin)], [bc[0], bc[1], max(bc[2] * k, tmin)])
            lo, hi = (k, hi) if cp_k < 0.75 * W else (lo, k)
        tc[2] = round(max(tc[2] * lo, tmin), 4); bc[2] = round(max(bc[2] * lo, tmin), 4)
        src["chord_thickness"] = f"thinned to {tc[2]:.3f} / {bc[2]:.3f} in so chords = 75% of {W:g} lb/ft"
    else:
        src["chord_thickness"] = "catalog" if "chords" in src and src["chords"].startswith("catalog") else "sized from weight"
    return dict(name=name, series=series, depth=d, tc=tc, bc=bc, seat=seat, seat_depth=sd, bearing_length=float(bl),
                filler=float(filler), bc_setback=float(sb), weight=float(W), sources=src)


# ---------------------------------------------------------------- geometry (OCP), inches in, millimetres out
def _angle(x0, L, y0, z0, b_vert, b_horz, t, sy, sz):
    """Angle prism along +x from x0, length L. Heel at (y0, z0); vertical leg b_vert along sy*y, horizontal leg b_horz
    along sz*z, thickness t."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Pnt, gp_Vec
    pts = [(y0 + sy * a, z0 + sz * c) for a, c in ((0, 0), (0, b_horz), (t, b_horz), (t, t), (b_vert, t), (b_vert, 0))]
    if sum(pts[k - 1][0] * pts[k][1] - pts[k][0] * pts[k - 1][1] for k in range(len(pts))) < 0:
        pts = pts[::-1]                                   # counter-clockwise in (y, z): face normal +x, positive volume
    poly = BRepBuilderAPI_MakePolygon()
    for a, c in pts:
        poly.Add(gp_Pnt(x0 * MM, a * MM, c * MM))
    poly.Close()
    f = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
    return BRepPrimAPI_MakePrism(f, gp_Vec(L * MM, 0, 0)).Shape()


def _bar(p, q, r):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir
    p = np.asarray(p, float); q = np.asarray(q, float)
    d = q - p; L = float(np.linalg.norm(d))
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*(p * MM)), gp_Dir(*(d / L))), r * MM, L * MM).Shape()


def layout(spec, L):
    """Web working points (x, y) in the joist frame and chord extents. JoistMtrl rule: rise = depth - 1 (points 0.5 in
    inside the chords), diagonals ~45 deg between bottom-chord panel points, first diagonal 6 in from the end."""
    d = spec["depth"]; rise = max(d - 1.0, 2.0); yt, yb = -0.5, -0.5 - rise
    sb = min(spec["bc_setback"], max(L / 2 - 6.0, 6.0))
    if L - 2 * sb < 8.0:
        sb = max((L - 8.0) / 2, 3.0)
    xb0, xb1 = sb, L - sb                                 # bottom chord extent
    pts = [(6.0, yt)]
    b0, b1 = xb0 + 4.0, xb1 - 4.0                         # end bottom-chord panel points
    if b1 - b0 < 1.0:
        mid = (b0 + b1) / 2; b0 = b1 = mid
        pts += [(mid, yb), (L - 6.0, yt)]
    else:
        n = max(1, int(round((b1 - b0) / (2 * rise))))
        pw = (b1 - b0) / n
        for i in range(n):
            pts += [(b0 + i * pw, yb), (b0 + i * pw + pw / 2, yt)]
        pts += [(b1, yb), (L - 6.0, yt)]
    return pts, xb0, xb1


def joist_local(spec, L, y_top=0.0, seats=(None, None)):
    """Local open-web joist (see module doc) -> (TopoDS_Compound in mm, info). L = work-line length (in). y_top = local y
    of the top of the top chord (0: work line = top of top chord, SDS/2 7.0-7.6; seat depth: work line = seat bottom,
    7.7+). seats = seat depth measured at the p1 / p2 end (support_seats), None -> spec seat depth."""
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRep import BRep_Builder
    L = float(L)
    if L < 12.0:
        raise ValueError("joist shorter than 12 in")
    tc, bc, seat = spec["tc"], spec["bc"], spec["seat"]
    sd, bl = spec["seat_depth"], min(spec["bearing_length"], L / 4)
    sds = [x if x else sd for x in seats]                 # per-end seat depth
    pts, xb0, xb1 = layout(spec, L)
    diag_len = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))
    a_ang = lambda g: g[2] * (g[0] + g[1] - g[2])
    seat_h = [max(seat[2] + 0.05, min(seat[0], x - tc[0])) for x in sds]   # seat vertical leg clipped under the top chord
    v_target = spec["weight"] * L / 12 / 0.2836
    v_fixed = 2 * a_ang(tc) * L + 2 * a_ang(bc) * (xb1 - xb0) + sum(2 * seat[2] * (h + seat[1] - seat[2]) * bl for h in seat_h)
    # round-bar web: JoistMtrl macro sizes 1/2-1 in for K joists; LH / DLH 3/4-1 1/2 in. Sized to the SJI mass remainder.
    rmin, rmax = (0.25, 0.5) if spec["series"] in ("K", "KCS") else (0.375, 0.75)
    a_web = max(v_target - v_fixed, 0.0) / max(diag_len, 1.0)
    r = min(max(math.sqrt(a_web / math.pi), rmin), rmax)
    gap = max(spec["filler"], 2 * r)                      # web bars sit between the back-to-back angles
    parts = []
    for s in (-1, 1):                                     # z side
        z0 = s * gap / 2
        parts.append(_angle(0.0, L, 0.0, z0, tc[0], tc[1], tc[2], -1, s))          # top chord: heel at the top
        parts.append(_angle(xb0, xb1 - xb0, -spec["depth"], z0, bc[0], bc[1], bc[2], 1, s))   # bottom chord
        for x_s, d_s, h_s in ((0.0, sds[0], seat_h[0]), (L - bl, sds[1], seat_h[1])):
            if d_s - tc[0] > seat[2]:                     # bearing seat under the top chord, heel at the seat bottom
                parts.append(_angle(x_s, bl, -d_s, z0, h_s, seat[1], seat[2], 1, s))
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        if math.hypot(x1 - x0, y1 - y0) > 1e-3:
            parts.append(_bar((x0, y0, 0.0), (x1, y1, 0.0), r))
    if y_top:
        from OCP.gp import gp_Trsf, gp_Vec
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        t = gp_Trsf(); t.SetTranslation(gp_Vec(0.0, y_top * MM, 0.0))
        parts = [BRepBuilderAPI_Transform(p, t, True).Shape() for p in parts]
    c = TopoDS_Compound(); bb = BRep_Builder(); bb.MakeCompound(c)
    for p in parts:
        bb.Add(c, p)
    v_web = math.pi * r * r * diag_len
    plf = (v_fixed + v_web) * 0.2836 / (L / 12)
    info = dict(tc="2L{:g}x{:g}x{:.3f}".format(*tc), bc="2L{:g}x{:g}x{:.3f}".format(*bc), web_dia=round(2 * r, 3),
                diagonals=len(pts) - 1, seat_depth=sd if sds[0] == sds[1] == sd else tuple(round(x, 3) for x in sds),
                bc_setback=round(xb0, 2), plf=round(plf, 2), plf_target=spec["weight"],
                solids=len(parts))
    return c, info


def work_line_datum(version):
    """'tc_top' for SDS/2 7.0-7.6 (joist ends sit the seat depth above the supporting beam's work line: WLCSC 7.331
    28/28, Greenwood 7.312 230+58+36 of 408 at +2.5/+5/+7.5 on W supports, NY Bridge 7.425 28 on W24/W16), 'seat_bottom'
    for 7.7+ (MORROW HS 7.720: 1,560 of 1,596 ends at +0.0, and SDS/2's own joist pieces put the seat bottom at y = 0)."""
    try:
        v = float(version or 0)
    except ValueError:
        v = 0.0
    return "seat_bottom" if v >= 7.7 else "tc_top"


def support_seats(mems, lo=2.0, hi=8.0):
    """{member id: (seat at p1, seat at p2)} measured from the job: height of each joist end above the work line of the
    beam it lands on (non-joist, non-vertical member whose work line passes within 6 in of the end in plan), kept when
    within [lo, hi] in (SDS/2 7.0-7.6 work line = top of top chord, so this is the seat depth the detailer modelled;
    WLCSC 76DLH-SP1: 7.42 in on W18s 4-5 in off the joist line although the record says 5.0; Greenwood 7.312: 36 LH ends
    at 7.5 for record 5.0; BAHAMAR 7.135: 75 K ends at 3.5, 21 at 5.0). Ends on nothing plausible -> None."""
    B = [b for b in mems if b.section is not None and b.section.d > 0 and not is_joist_designation(b.section.name)]
    if not B:
        return {}
    P1 = np.array([b.p1 for b in B], float); D = np.array([b.p2 for b in B], float) - P1
    with np.errstate(all="ignore"):
        LL = np.linalg.norm(D, axis=1)
        ok = np.isfinite(LL) & (LL > 1) & (np.abs(D[:, 2]) < 0.2 * np.maximum(LL, 1e-9))
    P1, D, LL = P1[ok], D[ok], LL[ok]
    out = {}
    for m in mems:
        if not is_joist_member(m):
            continue
        res = []
        for e in (np.asarray(m.p1, float), np.asarray(m.p2, float)):
            with np.errstate(all="ignore"):
                t = np.clip(((e - P1) * D).sum(1) / LL ** 2, 0, 1); C = P1 + t[:, None] * D
                h = np.linalg.norm((e - C)[:, :2], axis=1); dz = e[2] - C[:, 2]
            sel = (h < 6.0) & (dz >= lo - 1e-6) & (dz <= hi + 1e-6)
            res.append(round(float(dz[np.argmin(np.where(sel, h, 1e9))]) * 16) / 16 if sel.any() else None)
        if any(res):
            out[m.id] = tuple(res)
    return out


def joist_part(m, frame, version=None, seats=None):
    """(key, local compound in mm, (M, o) placement rows/origin in inches, spec, info) for a joist member, or None.
    frame = to_step.frame (x along the work line, u up, v across, roll applied). The key is shared by joists with the
    same designation, depth, seat and length (to 1/16 in), so each is written once as an assembly part."""
    if not is_joist_member(m):
        return None
    fr = frame(m, "X")
    if fr is None:
        return None
    p1, x, u, v, L = fr
    sec = m.section
    spec = spec_for(sec.name, sec.d, seat_from_job=round(sec.weight, 3) if sec.weight == sec.weight else None)
    if spec is None:
        return None
    datum = work_line_datum(version)
    y_top = spec["seat_depth"] if datum == "seat_bottom" else 0.0
    seats = tuple(seats) if seats and datum == "tc_top" else (None, None)
    try:
        local, info = joist_local(spec, L, y_top, seats)
    except Exception:
        return None
    info["datum"] = datum
    if any(seats):
        spec["sources"]["seat_depth"] = "measured from the supporting beams in the job"
    key = ("joist", sec.name, round(spec["depth"], 3), spec["seat_depth"], seats, round(L * 16) / 16, datum)
    return key, local, (np.array([x, u, v]), np.asarray(p1, float)), spec, info


def why(spec, info):
    """manifest reason (v5 pipelines: pieces-csv `standin` column)"""
    return (f"derived_from_designation: open-web joist, chords {info['tc']} / {info['bc']} ({spec['sources'].get('chords')}), "
            f"seat {_fmt(info['seat_depth'])} in ({spec['sources'].get('seat_depth')}), {info['plf']:g} lb/ft "
            f"(SJI {spec['weight']:g}); no chord/web data in the job")


def _fmt(v):
    return "/".join(f"{x:g}" for x in v) if isinstance(v, (tuple, list)) else f"{v:g}"


def label(m, n, spec, info):
    return (f"{m.type} #{n} / {m.section.name} (joist stand-in) [approx: open-web joist {spec['name']} derived from the "
            f"designation - chords {info['tc']} top / {info['bc']} bottom ({spec['sources'].get('chords')}), "
            f"{info['web_dia']:g} in round-bar web ({info['diagonals']} diagonals, JoistMtrl panel rule), seat "
            f"{_fmt(info['seat_depth'])} in ({spec['sources'].get('seat_depth')}), {info['plf']:g} lb/ft vs "
            f"{spec['weight']:g} ({spec['sources'].get('weight')}); the SDS2 job stores no chord/web data]")
