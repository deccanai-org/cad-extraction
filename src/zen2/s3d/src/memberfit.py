"""Member frame + physical-extent recovery.

S3D stores the part axis (STRUCTMemberPartAxisLin); the physical solid can be extended/trimmed at each end
(end cuts, cutbacks) -- only the ACIS body has the detail. CORESpatialIndex gives the solid's world bbox and
STRUCTMemberPartPris.cutLength its length. With the (exact) section frame known, every bbox face is linear in
the start/end parameter t0/t1 along the axis, so both can be solved; the fit is accepted only if
t1 - t0 == cutLength within tolerance and the bbox residual is small.
"""
import math
import numpy as np


def unit(v):
    v = np.asarray(v, float); n = np.linalg.norm(v)
    return v / n if n > 1e-12 else None


def section_dims(sec):
    d = (sec or {}).get('dims') or {}
    return d.get('bf') or d.get('Width'), d.get('d') or d.get('Depth')


def cardinal_offset(cp, B, D):
    if not cp or cp in (5, 10, 11) or cp > 15:
        return 0.0, 0.0
    if cp <= 9:
        col = (cp - 1) % 3; row = (cp - 1) // 3
        return (-B / 2, 0.0, B / 2)[col], (-D / 2, 0.0, D / 2)[row]
    return 0.0, 0.0


def frame(m):
    """-> (s, a, L, u, y) : start, unit axis, axis length, width axis (S3D u), up axis"""
    s, e = np.asarray(m['start'], float), np.asarray(m['end'], float)
    a = e - s; L = float(np.linalg.norm(a))
    if L < 1e-5:
        return None
    a = a / L
    up = m.get('o_vector')
    up = np.asarray(up, float) if up else None
    if up is None or np.linalg.norm(up) < 0.5 or abs(unit(up) @ a) > 0.999:
        up = np.array([0, 0, 1.0]) if abs(a[2]) < 0.999 else np.array([1.0, 0, 0])
        rl = math.radians(m.get('roll_deg') or 0.0)
        up = unit(up - a * (up @ a)); side = np.cross(up, a)
        up = up * math.cos(rl) + side * math.sin(rl)
    y = unit(up - a * (up @ a))
    u = np.cross(a, y) * (-1.0 if m.get('mirror') else 1.0)
    return s, a, L, u, y


def fit_extent(m, tol=0.004):
    """-> dict(t0, t1, residual, source) or None. t along the axis from the start point (m)."""
    bb = m.get('bbox'); sec = m.get('section')
    if not bb or not sec:
        return None
    B, D = section_dims(sec)
    if not (B and D):
        return None
    fr = frame(m)
    if fr is None:
        return None
    s, a, L, u, y = fr
    cx, cy = cardinal_offset(m.get('cardinal_point'), B, D)
    base = s - u * cx - y * cy
    corners = np.array([base + u * p + y * q for p in (-B / 2, B / 2) for q in (-D / 2, D / 2)])
    cmin, cmax = corners.min(0), corners.max(0)
    lo, hi = np.asarray(bb[:3], float), np.asarray(bb[3:], float)
    e0, w0, e1, w1 = [], [], [], []
    for k in range(3):
        ak = a[k]
        if abs(ak) < 0.05:
            continue
        if ak > 0:
            e0.append((lo[k] - cmin[k]) / ak); w0.append(abs(ak))
            e1.append((hi[k] - cmax[k]) / ak); w1.append(abs(ak))
        else:
            e1.append((lo[k] - cmin[k]) / ak); w1.append(abs(ak))
            e0.append((hi[k] - cmax[k]) / ak); w0.append(abs(ak))
    if not e0 or not e1:
        return None
    t0 = float(np.average(e0, weights=w0)); t1 = float(np.average(e1, weights=w1))
    # residual of the full predicted bbox
    P = np.concatenate([corners + a * t0, corners + a * t1])
    res = float(np.abs(np.concatenate([P.min(0), P.max(0)]) - np.asarray(bb, float)).max())
    cl = m.get('cut_length') or L
    ok = res < tol and abs((t1 - t0) - cl) < tol and t1 > t0
    return {'t0': round(t0, 5), 't1': round(t1, 5), 'residual': round(res, 5), 'cut_length_check': round((t1 - t0) - cl, 5), 'ok': bool(ok)}
