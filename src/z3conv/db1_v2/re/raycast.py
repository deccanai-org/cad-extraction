import numpy as np
def ray_tris(o, d, V, F, eps=1e-9):
    """all hit parameters t (line o + t d, any sign) against triangles V[F]"""
    v0 = V[F[:, 0]]; v1 = V[F[:, 1]]; v2 = V[F[:, 2]]
    e1 = v1 - v0; e2 = v2 - v0
    p = np.cross(d, e2); det = (e1 * p).sum(1)
    ok = np.abs(det) > eps
    inv = np.where(ok, 1.0 / np.where(ok, det, 1), 0)
    s = o - v0; u = (s * p).sum(1) * inv
    q = np.cross(s, e1); v = (q * d).sum(1) * inv
    t = (e2 * q).sum(1) * inv
    hit = ok & (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1 + 1e-7)
    return np.sort(t[hit])
