"""tube_probe.py DEC JOB SID,SID.. : piece record, section, B-rep measures, and the placing members (work points)."""
import sys, os, collections
import numpy as np
DEC, job = sys.argv[1], sys.argv[2]; sids = [int(x) for x in sys.argv[3].split(",")]
sys.path.insert(0, DEC)
import brep, to_step2 as T2
from piece_table import read_pieces, kind
from sds2job import read_shapes, read_members
from instances import material_instances
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
MM = 25.4
P = read_pieces(job); S = read_shapes(job); mems, _ = read_members(job)
place = collections.defaultdict(list)
for m in mems:
    try:
        _, inst = material_instances(job, m.id, P)
    except OSError:
        continue
    for sid, M, o in inst:
        if sid in sids: place[sid].append((m, M, o))
for s in sids:
    p = P[s]; r = brep.parse(open(os.path.join(job, "subm", str(s)), "rb").read())
    V, F = r
    sh = brep.solid(V, F, repair=True)
    sec = S.get(p["sec"])
    print(f"== piece {s} {p['name']} kind {kind(p)} L {p['L']:.3f} W {p['W']} T {p['T']} wt {p['wt']:.2f} repair {brep.LAST_REPAIR!r}")
    if sec: print(f"   section {sec.name} fam {sec.family} d {sec.d} bf {sec.bf} tw {sec.tw} tf {sec.tf} lb/ft {sec.weight}")
    used = sorted({i for f in F for i in f}); U = V[used]; ext = np.ptp(U, 0)
    print("   local ext", ext.round(3), "min", U.min(0).round(3), "max", U.max(0).round(3), "nv", len(V), "nf", len(F))
    if sh is not None:
        g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); vol = abs(g.Mass()) / MM ** 3
        g2 = GProp_GProps(); BRepGProp.SurfaceProperties_s(sh, g2); ar = abs(g2.Mass()) / MM ** 2
        te = 2 * vol / ar
        Ad = 2 * te * (sec.d + sec.bf - 2 * te) if sec else 0
        print(f"   brep vol {vol:.2f} in3 = {vol*0.2836:.1f} lb ({vol*0.2836/p['wt']:.3f}x SDS2 wt); area {ar:.1f}; 2V/A {te:.4f}; "
              f"length at that wall {vol/Ad:.1f} in; SDS2 wt as length of section lb/ft {p['wt']/sec.weight*12 if sec and sec.weight else 0:.1f} in")
    # centreline estimate: for each x-slab of the local frame, centroid of vertices
    for (m, M, o) in place[s][:3]:
        W = np.array([o + M.T @ v for v in U])
        p1, p2 = np.array(m.p1), np.array(m.p2)
        d1 = np.linalg.norm(W - p1, axis=1).min(); d2 = np.linalg.norm(W - p2, axis=1).min()
        print(f"   member {m.id} {m.type} p1 {np.round(p1,2)} p2 {np.round(p2,2)} |p2-p1| {np.linalg.norm(p2-p1):.2f}; "
              f"nearest brep vertex to p1 {d1:.2f} to p2 {d2:.2f}; placed ext {np.ptp(W,0).round(2)}")
    # sample the vertex cloud along its principal direction to estimate the path length (polyline through slab centroids)
    c = U.mean(0); _, _, vt = np.linalg.svd(U - c, full_matrices=False)
    t = (U - c) @ vt[0]; bins = np.linspace(t.min(), t.max(), 41); pts = []
    for a, b in zip(bins[:-1], bins[1:]):
        q = U[(t >= a) & (t <= b)]
        if len(q): pts.append(q.mean(0))
    pts = np.array(pts); print("   slab-centroid polyline length", round(float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum()), 1),
                               "end-to-end", round(float(np.linalg.norm(pts[-1] - pts[0])), 1))
