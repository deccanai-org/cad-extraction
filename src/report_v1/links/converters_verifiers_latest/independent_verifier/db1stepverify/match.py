"""Part <-> element matching between the STEP and a reference model (Tekla IFC export, or the re-decoded IFC).

Parts are compared by volume centroid and volume. A Tekla IFC export may be written relative to a base point and
rotated about Z, so a rigid transform (rotation about Z + translation) is solved first by voting on parts with
rare volume/height descriptors. Deterministic: fixed seed, sorted inputs."""
import re, math, collections
import numpy as np
from scipy.spatial import cKDTree
from . import config as C


def norm_name(s):
    s = (s or "").upper().replace(" ", "").replace("*", "X")
    return re.sub(r"X+", "X", s)


def name_overlap(a_names, b_names):
    ca, cb = collections.Counter(map(norm_name, a_names)), collections.Counter(map(norm_name, b_names))
    ca.pop("", None); cb.pop("", None)
    if not ca or not cb: return None
    common = sum(min(ca[k], cb[k]) for k in ca)
    return common / min(sum(ca.values()), sum(cb.values()))


def _rz(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def _corr(A, B):
    """candidate correspondences: parts with (nearly) the same volume and height that are rare in both models"""
    def key(p):
        return (int(round(math.log(max(p["volume_mm3"], 1.0)) / 0.002)), int(round((p["bbox"][5] - p["bbox"][2]) / 2.0)))
    ia = collections.defaultdict(list); ib = collections.defaultdict(list)
    for i, p in enumerate(A):
        if p.get("volume_mm3", 0) > 1e3: ia[key(p)].append(i)
    for j, p in enumerate(B):
        if p.get("volume_mm3", 0) > 1e3: ib[key(p)].append(j)
    out = []
    for k in sorted(ia):
        if len(ia[k]) > 4: continue
        cand = []
        for dv in (-1, 0, 1):
            for dz in (-1, 0, 1):
                cand += ib.get((k[0] + dv, k[1] + dz), [])
        if 0 < len(cand) <= 6:
            for i in ia[k]:
                for j in cand: out.append((i, j))
    return out[:40000]


def align(A, B, allow_rotation=True, min_votes=C.TRUTH_ALIGN_MIN_VOTES):
    """-> dict(R, t, votes, rot_deg, method) mapping A coordinates onto B (x_B = R x_A + t), or None."""
    corr = _corr(A, B)
    if not corr: return None
    CA = np.array([A[i]["centroid"] for i, _ in corr]); CB = np.array([B[j]["centroid"] for _, j in corr])
    angles = [0.0]
    if allow_rotation and len(corr) >= 2:
        rng = np.random.default_rng(C.SEED); n = len(corr); votes = collections.Counter()
        I = rng.integers(0, n, 60000); J = rng.integers(0, n, 60000)
        va = CA[J, :2] - CA[I, :2]; vb = CB[J, :2] - CB[I, :2]
        la, lb = np.linalg.norm(va, axis=1), np.linalg.norm(vb, axis=1)
        ok = (la > 500) & (np.abs(la - lb) < 0.002 * la + 2)
        ang = (np.degrees(np.arctan2(vb[ok, 1], vb[ok, 0]) - np.arctan2(va[ok, 1], va[ok, 0])) + 180) % 360 - 180
        for a in np.round(ang, 1): votes[float(a)] += 1
        angles += [a for a, _ in votes.most_common(3)]
    best = None
    for ang in dict.fromkeys(angles):
        R = _rz(ang); d = CB - CA @ R.T
        tv = collections.Counter(map(tuple, np.round(d / 5.0).astype(np.int64)))
        (tk, nv), = tv.most_common(1)
        t0 = np.array(tk, float) * 5.0
        res = np.linalg.norm(d - t0, axis=1); inl = res < 15.0
        if inl.sum() < min_votes: continue
        t = np.median(d[inl], axis=0)
        cand = dict(R=R, t=t, votes=int(inl.sum()), rot_deg=float(ang), method="identity" if ang == 0 and np.linalg.norm(t) < 1 else "rigid_z")
        if best is None or cand["votes"] > best["votes"]: best = cand
    return best


def displacement(A, B, R, t, unmatched_b, radius=1000.0):
    """For reference elements with no match: the nearest STEP part with the SAME profile (after alignment).
    Separates 'placed wrong' (same profile a little way off, e.g. half a section depth = an ignored Tekla position
    offset) from 'not converted' (no such part nearby). -> dict(displaced, absent, median_offset_mm, by_profile)"""
    if not unmatched_b: return dict(displaced=0, absent=0)
    CA = np.array([p["centroid"] for p in A]) @ R.T + t
    by = collections.defaultdict(list)
    for i, p in enumerate(A): by[norm_name(p.get("name"))].append(i)
    trees = {}
    off = []; prof = collections.Counter(); absent = 0; axes = []
    for j in unmatched_b:
        k = norm_name(B[j].get("profile") or B[j].get("name"))
        if k not in by: absent += 1; continue
        if k not in trees: trees[k] = (cKDTree(CA[by[k]]), by[k])
        tr, ids = trees[k]; d, ii = tr.query(B[j]["centroid"], distance_upper_bound=radius)
        if np.isfinite(d):
            off.append(float(d)); prof[k] += 1; axes.append(np.abs(np.array(B[j]["centroid"]) - CA[ids[ii]]))
        else:
            absent += 1
    out = dict(displaced=len(off), absent=absent)
    if off:
        out.update(median_offset_mm=float(np.median(off)), p90_offset_mm=float(np.percentile(off, 90)),
                   median_axis_offset_mm=[float(x) for x in np.median(np.array(axes), axis=0)], by_profile=prof.most_common(8))
    return out


def match(A, B, R=None, t=None, dist_tol=C.TRUTH_MATCH_DIST_MM, vol_tol=C.TRUTH_MATCH_VOL_TOL, near_tol=C.TRUTH_NEAR_DIST_MM):
    """Greedy one-to-one matching by centroid distance (after x_B = R x_A + t) with a volume check.
    -> dict(stats, pairs=[(i, j, dist, vol_ratio)], near=[(i,j,dist,vol_ratio)], unmatched_a, unmatched_b)"""
    R = np.eye(3) if R is None else R; t = np.zeros(3) if t is None else t
    if not A or not B:
        return dict(stats=dict(a=len(A), b=len(B), matched=0), pairs=[], near=[], unmatched_a=list(range(len(A))), unmatched_b=list(range(len(B))))
    CA = np.array([p["centroid"] for p in A]) @ R.T + t
    CB = np.array([p["centroid"] for p in B])
    VA = np.array([p.get("volume_mm3", 0.0) for p in A]); VB = np.array([p.get("volume_mm3", 0.0) for p in B])
    tree = cKDTree(CA)
    k = min(12, len(A))
    dd, ii = tree.query(CB, k=k, distance_upper_bound=near_tol)
    if k == 1: dd, ii = dd[:, None], ii[:, None]
    cand = []
    for j in range(len(B)):
        for d, i in zip(dd[j], ii[j]):
            if not np.isfinite(d): break
            vr = VA[i] / VB[j] if VB[j] > 0 else (1.0 if VA[i] == 0 else float("inf"))
            cand.append((float(d), abs(math.log(vr)) if 0 < vr < float("inf") else 99.0, int(i), j, vr))
    cand.sort()
    ua = np.ones(len(A), bool); ub = np.ones(len(B), bool); pairs = []; near = []
    for d, lv, i, j, vr in cand:                         # exact matches first: close AND same volume
        if ua[i] and ub[j] and d <= dist_tol and abs(vr - 1) <= vol_tol:
            ua[i] = ub[j] = False; pairs.append((i, j, d, vr))
    for d, lv, i, j, vr in cand:                         # then near misses (reported, not counted as matches)
        if ua[i] and ub[j]:
            ua[i] = ub[j] = False; near.append((i, j, d, vr))
    lo = CB.min(0) - 100; hi = CB.max(0) + 100
    inside = np.all((CA >= lo) & (CA <= hi), axis=1)
    m = len(pairs)
    stats = dict(a=len(A), b=len(B), matched=m, near=len(near), recall_b=m / len(B), precision_a=m / len(A),
                 a_inside_b_extent=int(inside.sum()), precision_a_inside=m / max(1, int(inside.sum())),
                 median_dist_mm=float(np.median([p[2] for p in pairs])) if pairs else None,
                 p95_dist_mm=float(np.percentile([p[2] for p in pairs], 95)) if pairs else None,
                 median_abs_vol_err=float(np.median([abs(p[3] - 1) for p in pairs])) if pairs else None)
    return dict(stats=stats, pairs=pairs, near=near, unmatched_a=[int(i) for i in np.flatnonzero(ua)],
                unmatched_b=[int(j) for j in np.flatnonzero(ub)])
