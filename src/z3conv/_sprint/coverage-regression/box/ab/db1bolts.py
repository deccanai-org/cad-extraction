"""Tekla bolt groups (old Xsteel engines 6.87 / 7.01 / 7.24) -> bolts + holes for db1step.convert_old.

Port of the owner's verified Windows pipeline (tekla-step-pipeline src/Converter.cs BuildBolt, Profiles.BoltDims):
  a bolt group is a part record with obj_type 10; its polygon points are the bolt positions in the group's csys
  (O + Ex*p0 + Ey*p1 + Ez*p2, Ez = Ex x Ey); profile MM<d>*<L>/... gives the shank diameter and length;
  each bolt = shank (d, from -L/2 to +L/2 along Ez) + hex head (across flats 1.6 d, height 0.65 d) below + hex nut
  (0.8 d) above.
Interface (stable; also used by the Tekla new-engine improver):
  bolts_of(member_record) -> [{c, ex, ey, ez, d, L, pid, standard}]   (record keys used: O, xr, y, prof, old_poly, pid, mat)
  outline(kind, params) -> (outer, [inners]) | None                  section outline in the IFC profile plane
  HoleIndex(bolts).holes_for(frame, depth, region) -> [bolt index]   frame = (origin, Z, X) world, extrusion 0..depth along Z
  ply_check(frame, depth, region, bolt) -> (tmin, tmax) | None       plies' extent along the bolt axis (shank centre = 0)
  clearance(d) -> mm                                                  ISO 273 normal series
  db1step.IfcOut.bolt_group(name, bolts) writes the bolts (faceted polyhedra); db1step adds hole cuts to the parts.
Holes (z3 addition; the Windows pipeline does not cut holes): every written part whose solid the shank segment passes
through gets a cylinder cut of diameter d + nominal clearance (ISO 273 normal series: +1 up to M12, +2 up to M24, +3 above)
along the bolt axis, length L. Parts are tested with their exact 2D section outline (RECT, CIRC, CHS, RHS, I, L, U,
arbitrary polylines / contour plates); sections without an exact outline are not cut (counted).
"""
import math, re, os, json
import numpy as np

NUM = r'(\d+(?:\.\d+)?)'
P_BOLTPROF = re.compile(r'^MM\s*' + NUM + r'\s*\*\s*' + NUM)
BOLT_ENGINES = {'6.87', '7.01', '7.24'}


def bolt_dims(prof):
    m = P_BOLTPROF.match((prof or '').strip().upper())
    if not m:
        return None
    d, L = float(m.group(1)), float(m.group(2))
    return (d, L) if 0 < d <= 100 and 0 < L <= 2000 else None


def clearance(d):
    return 1.0 if d <= 12 else (2.0 if d <= 24 else 3.0)


def hole_clearance(b):
    sg = b.get('std')
    return sg['hole_clearance'] if sg else clearance(b['d'])


def bolt_tolerance(prof):
    """old engines: hole tolerance = 4th '/'-field of the bolt profile string MM<d>*<L>/a/b/<tol>/... (data-3 MoldTek models:
    M12-M22 -> 2, M27 -> 3 mm, Tekla's usual settings); None when absent or implausible"""
    try:
        t = float((prof or '').split('/')[3])
    except (IndexError, ValueError):
        return None
    return t if 0 < t <= 10 else None


def hole_diameter(b):
    """-> (diameter mm, decoded?) : stored diameter + decoded tolerance (as the Tekla model cuts it), else d + standard clearance"""
    if b.get('tol') is not None:
        return b.get('d_stored', b['d']) + b['tol'], True
    return b['d'] + hole_clearance(b), False


def frame_axes(m):
    ex = np.asarray(m['xr'], float); ex = ex / np.linalg.norm(ex)
    ey = np.asarray(m['y'], float); ey = ey - (ey @ ex) * ex; ey = ey / np.linalg.norm(ey)
    ez = np.cross(ex, ey); ez = ez / np.linalg.norm(ez)
    return ex, ey, ez


def bolt_standard(m):
    """bolt grade / standard as stored in the bolt group's material field (old engines): 'A325', 'A307', '8.8XOX', 'HEX B/N M16', ..."""
    return (m.get('mat') or '').strip() or None


_BC = {}


def model_catalog():
    """the model folder's own Tekla bolt catalogs (assdb.db + screwdb.db, decoded by the profiles agent; validated vs Tekla IFC):
    bolt_catalog.json models[sha256 of the DB1] -> {assembly: {sizes: {d: {bolt {k, s, e}, nut1 {m, s}, washer1 {t, di, do}}}}}"""
    if 'm' not in _BC:
        try:
            _BC['m'] = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bolt_catalog.json'))).get('models', {})
        except Exception:
            _BC['m'] = {}
    return _BC['m'].get(os.environ.get('DB1_SHA256', ''), {})


def catalog_geometry(standard, d):
    """exact head / nut / washer of the bolt assembly named in the bolt group (its standard string) from the model's own catalog"""
    a = model_catalog().get((standard or '').strip())
    if not a:
        return None
    sz = a.get('sizes') or {}
    e = sz.get(f'{float(d):.1f}') or sz.get(str(d)) or sz.get(f'{float(d):g}')
    if not e or not e.get('bolt') or not (e.get('nut1') or {}).get('m'):
        return None
    # coverage-regression fix: catalog builder records an unresolved head as {'ambiguous': n} (no s / k). Such an entry is
    # not exact catalog geometry -> None (caller falls back to the decoded-standard table) instead of KeyError 's', which
    # crashed the whole decode (convert_error) for 7c68f0c9874e / 3585d86a380d / 48e010c8ec25 on code z3-db1-2026-10-01i
    if not isinstance(e['bolt'], dict) or e['bolt'].get('s') is None or e['bolt'].get('k') is None:
        return None
    b, n1, w1 = e['bolt'], e['nut1'], e.get('washer1') or {}
    return {'d': float(d), 'head_af': b['s'], 'head_h': b['k'], 'nut_af': n1.get('s', b['s']), 'nut_h': n1['m'],
            'washer_t': w1.get('t'), 'washer_od': w1.get('do'), 'washer_id': w1.get('di'), 'hole_clearance': clearance(float(d)),
            'family': f"model catalog ({a.get('bolt_std') or '?'}, nut {a.get('nut1')}, washer {a.get('washer1')})", 'mapping': standard,
            'delta_mm': 0.0, 'source': 'model_catalog'}


def bolt_fields(prof):
    """old-engine bolt string MM<d>*<L>/f1/f2/f3/f4/f5/f6/f7/f8/f9/f10 (semantics from the Tekla improver, validated against Tekla IFC on 7.82
    and against the decoded ply geometry on data-3 6.87 / 7.01): f3 hole tolerance, f6 grip-centre offset along group z, f8 assembly
    flags (decimal digits d5..d0: d5 = holes only, washers = d4 + d3 + d2, nuts = d1 + d0), f10 grip length"""
    p = (prof or '').split('/')
    out = {}
    try:
        out['f6'] = float(p[6]); out['f10'] = float(p[10])
    except (IndexError, ValueError):
        pass
    try:
        fl = '%06d' % int(float(p[8]))
        dd = [int(c) for c in fl[-6:]]                      # d5 d4 d3 d2 d1 d0
        out['holes_only'] = dd[0] == 1
        out['wash_head'] = dd[1]; out['wash_nut'] = dd[3]; out['wash_2'] = dd[2]; out['nuts'] = dd[4] + dd[5]   # d4 head, d3 washer 2, d2 nut
    except (IndexError, ValueError):
        pass
    return out


def bolts_of(m):
    """bolt group part record -> list of bolts {c (shank centre), ex, ey, ez, d, L, pid, standard, std, tol, axial_decoded, head_up,
    grip (lo, hi along ez relative to the bolt point), holes_only, wash_head, wash_nut, nuts}"""
    dl = bolt_dims(m.get('prof'))
    if not dl:
        return []
    d, L = dl
    ex, ey, ez = frame_axes(m)
    O = np.asarray(m['O'], float)
    pts = m.get('old_poly') or [(0.0, 0.0, 0.0)]
    out = []
    seen = set()
    for p in pts:
        p = tuple(float(x) for x in (list(p) + [0, 0, 0])[:3])
        k = tuple(round(x, 3) for x in p)
        if k in seen:                       # duplicate polygon points (closing point) are one bolt
            continue
        seen.add(k)
        c = O + ex * p[0] + ey * p[1] + ez * p[2]
        sg = catalog_geometry(bolt_standard(m), d) or standard_geometry(bolt_standard(m), d)
        bf = bolt_fields(m.get('prof'))
        b = {'c': c, 'ex': ex, 'ey': ey, 'ez': ez, 'd': sg['d'] if sg else d, 'd_stored': d, 'L': L, 'pid': m.get('pid'),
             'standard': bolt_standard(m), 'std': sg, 'tol': bolt_tolerance(m.get('prof')), 'holes_only': bf.get('holes_only', False),
             'wash_head': bf.get('wash_head', 0), 'wash_nut': bf.get('wash_nut', 0), 'wash_2': bf.get('wash_2', 0), 'nuts': bf.get('nuts', 1),
             'axial_decoded': False}
        if 'f6' in bf and bf.get('f10', 0) > 0:
            # head on the +z face: head underside at f6 + f10/2 (+ a head-side washer), shank from there toward -z for length L
            zt = bf['f6'] + bf['f10'] / 2
            zh = zt + (washer_t(b) if b['wash_head'] else 0.0)
            b['grip'] = (bf['f6'] - bf['f10'] / 2, zt); b['zh'] = zh
            b['c'] = c + ez * (zh - L / 2); b['axial_decoded'] = True; b['head_up'] = True
        out.append(b)
    return out


# ------------------------------------------------------------------ 2D section outlines (IFC2X3 parameterized profile conventions:
# origin at the bounding-box centre; I/U/L/T built from their parameters)
def circle(r, n=32):
    return [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def outline(kind, v):
    """-> (outer polygon, [inner polygons]) in the profile plane, or None when no exact outline is known"""
    g = lambda i: float(v[i]) if i < len(v) and v[i] is not None else None
    try:
        if kind == 'RECT':
            x, y = g(0), g(1)
            return [(-x / 2, -y / 2), (x / 2, -y / 2), (x / 2, y / 2), (-x / 2, y / 2)], []
        if kind == 'CIRC':
            return circle(g(0)), []
        if kind == 'CHS':
            r, t = g(0), g(1)
            return circle(r), ([circle(r - t)] if 0 < t < r else [])
        if kind == 'RHS':
            x, y, t = g(0), g(1), g(2)
            inner = [(-x / 2 + t, -y / 2 + t), (x / 2 - t, -y / 2 + t), (x / 2 - t, y / 2 - t), (-x / 2 + t, y / 2 - t)] if 0 < t < min(x, y) / 2 else None
            return [(-x / 2, -y / 2), (x / 2, -y / 2), (x / 2, y / 2), (-x / 2, y / 2)], ([inner] if inner else [])
        if kind == 'I':
            b, h, tw, tf = g(0), g(1), g(2), g(3)
            return [(-b / 2, -h / 2), (b / 2, -h / 2), (b / 2, -h / 2 + tf), (tw / 2, -h / 2 + tf), (tw / 2, h / 2 - tf), (b / 2, h / 2 - tf),
                    (b / 2, h / 2), (-b / 2, h / 2), (-b / 2, h / 2 - tf), (-tw / 2, h / 2 - tf), (-tw / 2, -h / 2 + tf), (-b / 2, -h / 2 + tf)], []
        if kind == 'U':
            h, b, tw, tf = g(0), g(1), g(2), g(3)
            return [(-b / 2, -h / 2), (b / 2, -h / 2), (b / 2, -h / 2 + tf), (-b / 2 + tw, -h / 2 + tf), (-b / 2 + tw, h / 2 - tf),
                    (b / 2, h / 2 - tf), (b / 2, h / 2), (-b / 2, h / 2)], []
        if kind == 'L':
            h, b, t = g(0), (g(1) or g(0)), g(2)
            return [(-b / 2, -h / 2), (b / 2, -h / 2), (b / 2, -h / 2 + t), (-b / 2 + t, -h / 2 + t), (-b / 2 + t, h / 2), (-b / 2, h / 2)], []
        if kind in ('ARB', 'ARBV'):
            return [(float(a), float(b)) for a, b in v], []
    except (TypeError, ValueError):
        return None
    return None


def _inside(pt, poly):
    x, y = pt; n = len(poly); c = False
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-300) + x1:
            c = not c
    return c


def _seg_cross(a, b, c, d):
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return (o1 * o2 < 0) and (o3 * o4 < 0)


def seg_hits_region(a, b, outer, inners):
    """2D segment a-b touches material of the region (outer minus inners)"""
    def in_mat(p):
        return _inside(p, outer) and not any(_inside(p, h) for h in inners)
    if in_mat(a) or in_mat(b):
        return True
    for poly in [outer] + inners:
        n = len(poly)
        for i in range(n):
            if _seg_cross(a, b, poly[i], poly[(i + 1) % n]):
                return True
    # segment fully in the void of a hollow section without touching a wall is impossible for a straight line that
    # enters the outer polygon (it would cross the outer boundary); a=b case handled above
    return False


def part_hit(frame, depth, region, bolt, margin=0.0):
    """does the bolt shank segment pass through the extruded part? frame = (origin, Z, X) world; extrusion along local Z 0..depth"""
    o, Z, X = (np.asarray(x, float) for x in frame)
    Z = Z / np.linalg.norm(Z); X = X - (X @ Z) * Z; X = X / np.linalg.norm(X); Y = np.cross(Z, X)
    R = np.stack([X, Y, Z], 1)
    p0 = R.T @ (bolt['c'] - bolt['ez'] * bolt['L'] / 2 - o)
    p1 = R.T @ (bolt['c'] + bolt['ez'] * bolt['L'] / 2 - o)
    # clip to the slab 0 <= z <= depth
    t0, t1 = 0.0, 1.0
    dz = p1[2] - p0[2]
    for lim, sgn in ((0.0 - margin, 1), (depth + margin, -1)):
        if abs(dz) < 1e-12:
            if (p0[2] - lim) * sgn < 0:
                return False
            continue
        t = (lim - p0[2]) / dz
        if sgn * dz > 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
    if t0 > t1:
        return False
    a = p0 + (p1 - p0) * t0; b = p0 + (p1 - p0) * t1
    outer, inners = region
    return seg_hits_region((a[0], a[1]), (b[0], b[1]), outer, inners)


def aabb_of_part(frame, depth, region):
    o, Z, X = (np.asarray(x, float) for x in frame)
    Z = Z / np.linalg.norm(Z); X = X - (X @ Z) * Z; X = X / np.linalg.norm(X); Y = np.cross(Z, X)
    P = np.array(region[0])
    lo2, hi2 = P.min(0), P.max(0)
    cs = []
    for x in (lo2[0], hi2[0]):
        for y in (lo2[1], hi2[1]):
            for z in (0.0, depth):
                cs.append(o + X * x + Y * y + Z * z)
    cs = np.array(cs)
    return cs.min(0), cs.max(0)


class HoleIndex:
    """bolt shank segments with an AABB prefilter"""
    def __init__(self, bolts):
        self.b = bolts
        if bolts:
            a = np.array([b['c'] - b['ez'] * b['L'] / 2 for b in bolts]); c = np.array([b['c'] + b['ez'] * b['L'] / 2 for b in bolts])
            r = np.array([b['d'] for b in bolts])[:, None]
            self.lo = np.minimum(a, c) - r; self.hi = np.maximum(a, c) + r
        self.hits = [0] * len(bolts)
        self.ply_spans = [[] for _ in bolts]

    def candidates(self, lo, hi):
        if not self.b:
            return []
        m = np.all(self.hi >= lo, axis=1) & np.all(self.lo <= hi, axis=1)
        return list(np.nonzero(m)[0])

    def holes_for(self, frame, depth, region):
        lo, hi = aabb_of_part(frame, depth, region)
        out = []
        for i in self.candidates(lo, hi):
            b = self.b[i]
            if part_hit(frame, depth, region, b):
                out.append(i); self.hits[i] += 1
        return out


def ply_check(frame, depth, region, bolt, step=0.5):
    """extent of the part's material along the bolt axis (min, max of t in [-L/2, L/2] where the axis is inside material)"""
    o, Z, X = (np.asarray(x, float) for x in frame)
    Z = Z / np.linalg.norm(Z); X = X - (X @ Z) * Z; X = X / np.linalg.norm(X); Y = np.cross(Z, X)
    R = np.stack([X, Y, Z], 1)
    L = bolt['L']; ts = np.arange(-L / 2 - 2 * bolt['d'], L / 2 + 2 * bolt['d'] + step, step)
    P = (bolt['c'][None, :] + bolt['ez'][None, :] * ts[:, None] - o) @ R
    outer, inners = region
    ins = [(0 <= p[2] <= depth) and _inside((p[0], p[1]), outer) and not any(_inside((p[0], p[1]), h) for h in inners) for p in P]
    tt = ts[np.array(ins)]
    return (float(tt.min()), float(tt.max())) if len(tt) else None


# ------------------------------------------------------------------ standard bolt assembly tables (head / nut), z3 rules.json bolt_standard_geometry_exact
# ASTM A325 / A490 heavy hex structural bolt + A563 heavy hex nut (ASME B18.2.6, AISC Manual Table 7-14), inches:
#   D: (head across flats F, head height H, nut across flats W, nut thickness T)
_IN = 25.4
ASTM_HEAVY = {0.5: (0.875, 5 / 16, 0.875, 31 / 64), 0.625: (1.0625, 25 / 64, 1.0625, 39 / 64), 0.75: (1.25, 15 / 32, 1.25, 47 / 64),
              0.875: (1.4375, 35 / 64, 1.4375, 55 / 64), 1.0: (1.625, 39 / 64, 1.625, 63 / 64), 1.125: (1.8125, 11 / 16, 1.8125, 1 + 7 / 64),
              1.25: (2.0, 25 / 32, 2.0, 1 + 7 / 32), 1.375: (2.1875, 27 / 32, 2.1875, 1 + 11 / 32), 1.5: (2.375, 15 / 16, 2.375, 1 + 15 / 32)}
# ASTM A307 hex bolt (ASME B18.2.1) + hex nut (ASME B18.2.2), inches
ASTM_HEX = {0.5: (0.75, 11 / 32, 0.75, 7 / 16), 0.625: (0.9375, 27 / 64, 0.9375, 35 / 64), 0.75: (1.125, 0.5, 1.125, 41 / 64),
            0.875: (1.3125, 37 / 64, 1.3125, 0.75), 1.0: (1.5, 43 / 64, 1.5, 55 / 64), 1.125: (1.6875, 0.75, 1.6875, 31 / 32),
            1.25: (1.875, 27 / 32, 1.875, 1 + 1 / 16), 1.375: (2.0625, 29 / 32, 2.0625, 1 + 11 / 64), 1.5: (2.25, 1.0, 2.25, 1 + 9 / 32)}
# ISO 4014 hex head (s, k) + ISO 4032 hex nut (s, m), mm
ISO_HEX = {12: (18, 7.5, 18, 10.8), 16: (24, 10, 24, 14.8), 20: (30, 12.5, 30, 18), 22: (34, 14, 34, 19.4), 24: (36, 15, 36, 21.5),
           27: (41, 17, 41, 23.8), 30: (46, 18.7, 46, 25.6), 36: (55, 22.5, 55, 31)}


def standard_geometry(standard, d):
    """-> dict(d=true shank diameter mm, head_af, head_h, nut_af, nut_h, hole_clearance, family, mapping) when the decoded standard has a
    table entry for this diameter, else None (nominal proportions stay, tagged approx).
    ASTM grades come only in inch sizes: the stored metric-rounded diameter maps to the nearest inch size within 1 mm (owner-approved)."""
    s = (standard or '').upper().replace(' ', '')
    fam = None
    if s.startswith(('A325', 'A490', 'F1852', 'F2280')):
        fam, tab, unit = 'ASTM heavy hex (B18.2.6) + A563 heavy hex nut', ASTM_HEAVY, _IN
    elif s.startswith('A307'):
        fam, tab, unit = 'ASTM hex (B18.2.1) + hex nut (B18.2.2)', ASTM_HEX, _IN
    elif re.match(r'^(4\.6|5\.6|8\.8|10\.9|12\.9)', s):
        fam, tab, unit = 'ISO 4014 hex head + ISO 4032 nut', ISO_HEX, 1.0
    if not fam:
        return None
    best = min(tab, key=lambda k: abs(k * unit - d))
    delta = abs(best * unit - d)
    if delta > 1.0:
        return None
    F, H, W, T = (x * unit for x in tab[best])
    dd = best * unit
    hole = (1 / 16 * _IN) if unit == _IN else clearance(dd)              # AISC standard hole d + 1/16 in; ISO 273 normal series
    return {'d': dd, 'head_af': F, 'head_h': H, 'nut_af': W, 'nut_h': T, 'hole_clearance': hole, 'family': fam,
            'mapping': f'{d:g} mm stored -> {best:g} in' if unit == _IN else f'M{best:g}', 'delta_mm': round(delta, 3)}


# washers: ISO 7089 (metric) / ASTM F436 (inch) outside diameter; thickness nominal (tagged approx)
ISO_WASHER = {12: (24, 2.5), 16: (30, 3), 20: (37, 3), 22: (39, 3), 24: (44, 4), 27: (50, 4), 30: (56, 4), 36: (66, 5)}
F436_OD_IN = {0.5: 1.0625, 0.625: 1.3125, 0.75: 1.46875, 0.875: 1.75, 1.0: 2.0, 1.125: 2.25, 1.25: 2.5, 1.375: 2.75, 1.5: 3.0}


def washer_dims(b):
    """-> (outside diameter, thickness) mm; from the model's own catalog, else ISO 7089 (metric), else F436 OD + nominal thickness"""
    sg = b.get('std'); d = b['d']
    if sg and sg.get('source') == 'model_catalog' and sg.get('washer_od') and sg.get('washer_t'):
        return float(sg['washer_od']), float(sg['washer_t'])
    if sg and 'ASTM' in sg['family']:
        k = min(F436_OD_IN, key=lambda x: abs(x * _IN - d))
        if abs(k * _IN - d) < 0.5:
            return F436_OD_IN[k] * _IN, 0.136 * _IN
    k = min(ISO_WASHER, key=lambda x: abs(x - d))
    if abs(k - d) < 0.5:
        return float(ISO_WASHER[k][0]), float(ISO_WASHER[k][1])
    return 2.0 * d, 0.15 * d


def washer_t(b):
    return washer_dims(b)[1]


def washer_exact(b):
    """washer dimensions from a source catalog or a standard with a single nominal thickness (ISO 7089); F436 gives only a range"""
    sg = b.get('std') or {}
    if sg.get('source') == 'model_catalog' and sg.get('washer_od') and sg.get('washer_t'):
        return True
    if sg and 'ISO' in sg.get('family', ''):
        k = min(ISO_WASHER, key=lambda x: abs(x - b['d']))
        return abs(k - b['d']) < 0.5
    return False
