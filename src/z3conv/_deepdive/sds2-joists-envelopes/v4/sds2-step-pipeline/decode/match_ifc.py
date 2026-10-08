"""Fit mem/ end points (job inches) to IFC axes (site metres) and report match quality.

Hypothesis: mem record = [R1 3x3 @0x00][P1 xyz @0x48] ... [R2 3x3 @0x88][P2 xyz @0xD0], big-endian doubles.
usage: python match_ifc.py <job_dir> <ifc_axes.csv>
"""
import os, sys, struct, csv, itertools
import numpy as np

job, axes = sys.argv[1], sys.argv[2]
IN = 0.0254
md = os.path.join(job, "mem")
mem = {}
for n in os.listdir(md):
    if n.isdigit():
        b = open(os.path.join(md, n), "rb").read()
        if len(b) >= 0xE8:
            d = struct.unpack(">29d", b[:0xE8])
            mem[int(n)] = (np.array(d[9:12]), np.array(d[26:29]))
print("mem records with points:", len(mem))

ifc = [r for r in csv.DictReader(open(axes))]
A = np.array([[float(r[k]) for k in ("ax", "ay", "az")] for r in ifc])
B = np.array([[float(r[k]) for k in ("bx", "by", "bz")] for r in ifc])
print("IFC z range (in):", (np.r_[A[:, 2], B[:, 2]] / IN).min().round(1), (np.r_[A[:, 2], B[:, 2]] / IN).max().round(1))
allp = np.array([p for pq in mem.values() for p in pq])
print("mem z range (in):", allp[:, 2].min().round(1), allp[:, 2].max().round(1))

# vertical members on both sides -> 2D point sets (x,y)
iv = np.array([(a[:2] + b[:2]) / 2 / IN for a, b in zip(A, B) if np.linalg.norm(a[:2] - b[:2]) < 0.01 and abs(a[2] - b[2]) > 1])
mv = np.array([(p[:2] + q[:2]) / 2 for p, q in mem.values() if np.linalg.norm(p[:2] - q[:2]) < 0.5 and abs(p[2] - q[2]) > 40])
iv = np.unique(iv.round(1), axis=0); mv = np.unique(mv.round(1), axis=0)
print("vertical xy: ifc", len(iv), "mem", len(mv))

# brute-force 2D rigid fit: try pairs of mem points vs pairs of ifc points with equal distance
from scipy.spatial import cKDTree
ti = cKDTree(iv)
best = (0, None)
rng = np.random.default_rng(0)
for _ in range(4000):
    i, j = rng.choice(len(mv), 2, replace=False)
    dm = np.linalg.norm(mv[i] - mv[j])
    if dm < 200: continue
    k = rng.integers(len(iv))
    # candidates l with same distance from iv[k]
    dd = np.linalg.norm(iv - iv[k], axis=1)
    for l in np.where(abs(dd - dm) < 0.5)[0][:20]:
        am = np.arctan2(*(mv[j] - mv[i])[::-1]); ai = np.arctan2(*(iv[l] - iv[k])[::-1])
        th = ai - am
        R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
        t = iv[k] - R @ mv[i]
        dist, _ = ti.query(mv @ R.T + t)
        score = (dist < 1.0).sum()
        if score > best[0]:
            best = (score, (R, t, th))
score, (R, t, th) = best
print(f"2D fit: {score}/{len(mv)} mem column lines land within 1in of an IFC column; rotation {np.degrees(th):.3f} deg, shift {t.round(2)} in")

# apply to all mem end points, match to IFC end points (unordered)
def to_site(p):
    return np.r_[R @ p[:2] + t, p[2]]
ie = np.c_[A / IN, B / IN]
tree = cKDTree(np.r_[A, B] / IN)
matched = within = 0
errs = []
for n, (p, q) in mem.items():
    sp, sq = to_site(p), to_site(q)
    d1, i1 = tree.query(sp); d2, i2 = tree.query(sq)
    e1, e2 = i1 % len(A), i2 % len(A)
    if e1 == e2 and i1 != i2:
        matched += 1; errs.append(max(d1, d2))
print(f"mem records whose BOTH end points hit the two ends of the same IFC member: {matched}/{len(mem)}")
if errs:
    e = np.array(errs); print("  end-point error (in): median", np.median(e).round(3), "p90", np.percentile(e, 90).round(3))
