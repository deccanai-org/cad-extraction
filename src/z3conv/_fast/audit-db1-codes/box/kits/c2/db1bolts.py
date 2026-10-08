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
import math, re
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


def frame_axes(m):
    ex = np.asarray(m['xr'], float); ex = ex / np.linalg.norm(ex)
    ey = np.asarray(m['y'], float); ey = ey - (ey @ ex) * ex; ey = ey / np.linalg.norm(ey)
    ez = np.cross(ex, ey); ez = ez / np.linalg.norm(ez)
    return ex, ey, ez


def bolt_standard(m):
    """bolt grade / standard as stored in the bolt group's material field (old engines): 'A325', 'A307', '8.8XOX', 'HEX B/N M16', ..."""
    return (m.get('mat') or '').strip() or None


def bolts_of(m):
    """bolt group part record -> list of bolts {c, ex, ey, ez, d, L, pid, standard}"""
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
        out.append({'c': c, 'ex': ex, 'ey': ey, 'ez': ez, 'd': d, 'L': L, 'pid': m.get('pid'), 'standard': bolt_standard(m)})
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
