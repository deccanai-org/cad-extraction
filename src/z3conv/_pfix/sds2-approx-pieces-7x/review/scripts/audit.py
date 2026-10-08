#!/usr/bin/env python3
"""audit.py DECODE_DIR JOB OUT.json [BASE.json]
Independent reviewer audit of brep_placed() for every unique placed plate / rolled / BLT piece of a job.
Per piece: exact or not, why, repair / identity / negative-weight notes, volume, area, face count, bbox.
With BASE.json (the same audit with the base decoder): for every piece exact here but not in BASE, a no-fabrication
test: the solid is triangulated and every triangle centroid must lie on a face stored in the piece file (same plane
within 0.003 in, inside the face by the even-odd rule on its full stored entry list, or within 0.003 in of its
boundary). Pieces exact in both must have identical volume / face count; pieces exact in BASE must stay exact."""
import sys, os, json, collections, time
import numpy as np

DEC, job, out = sys.argv[1], sys.argv[2], sys.argv[3]
basef = sys.argv[4] if len(sys.argv) > 4 else None
sys.path.insert(0, DEC)
import to_step2 as T2, brep
from piece_table import read_pieces, kind
from sds2job import read_members, REFERENCE_TYPES, read_shapes
from instances import material_instances
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCP.TopoDS import TopoDS
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRep import BRep_Tool
from OCP.TopLoc import TopLoc_Location
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer

MM = 25.4
T2.USE_HOLES = False
T2.SHARED = True
t0 = time.time()
pieces = read_pieces(job)
mems, _ = read_members(job)
try:
    T2.SHAPES = read_shapes(job)          # convert() sets this in the patched build; harmless otherwise
except Exception:
    pass
mtype = {m.id: m.type for m in mems}
cnt = collections.Counter()
for n in sorted(mtype):
    if mtype[n] == "Ref Point" or mtype[n] in REFERENCE_TYPES:
        continue
    try:
        _, inst = material_instances(job, n, pieces)
    except OSError:
        continue
    for sid, M, o in inst:
        p = pieces[sid]; k = kind(p)
        if (k in ("plate", "rolled") and not T2.TURNED.match(p["name"]) or p["name"].startswith("BLT")) \
                and not p["name"].startswith("Conc"):
            cnt[sid] += 1


def props(sh):
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); vol = abs(g.Mass()) / MM ** 3
    g2 = GProp_GProps(); BRepGProp.SurfaceProperties_s(sh, g2); ar = abs(g2.Mass()) / MM ** 2
    nf = 0; ex = TopExp_Explorer(sh, TopAbs_FACE)
    while ex.More(): nf += 1; ex.Next()
    ns = 0; ex = TopExp_Explorer(sh, TopAbs_SOLID)
    while ex.More(): ns += 1; ex.Next()
    bb = Bnd_Box(); BRepBndLib.Add_s(sh, bb); a, b = bb.CornerMin(), bb.CornerMax()
    return dict(vol=vol, area=ar, nfaces=nf, nsolids=ns, valid=bool(BRepCheck_Analyzer(sh).IsValid()),
                bbox=[round(x / MM, 4) for x in (a.X(), a.Y(), a.Z(), b.X(), b.Y(), b.Z())])


def tris(sh):
    BRepMesh_IncrementalMesh(sh, 0.05, False, 0.5, False)
    C, A, N = [], [], []
    ex = TopExp_Explorer(sh, TopAbs_FACE)
    while ex.More():
        f = (getattr(TopoDS, 'Face_s', None) or TopoDS.Face)(ex.Current()); loc = TopLoc_Location()
        tr = BRep_Tool.Triangulation_s(f, loc)
        if tr is not None:
            T = loc.Transformation()
            P = np.array([[q.X(), q.Y(), q.Z()] for q in (tr.Node(i).Transformed(T) for i in range(1, tr.NbNodes() + 1))]) / MM
            for i in range(1, tr.NbTriangles() + 1):
                a, b, c = tr.Triangle(i).Get()
                p0, p1, p2 = P[a - 1], P[b - 1], P[c - 1]
                cr = np.cross(p1 - p0, p2 - p0); ar = np.linalg.norm(cr) / 2
                if ar <= 0: continue
                C.append((p0 + p1 + p2) / 3); A.append(ar); N.append(cr / (2 * ar))
        ex.Next()
    return np.array(C), np.array(A), np.array(N)


def stored_faces(V, F):
    out = []
    for f in F:
        seq = [f[0]] + [f[i] for i in range(1, len(f)) if f[i] != f[i - 1]]
        if len(seq) > 1 and seq[-1] == seq[0]: seq = seq[:-1]
        if len(seq) < 3: continue
        P = V[seq]; c = P.mean(0)
        nv = sum(np.cross(P[k] - c, P[(k + 1) % len(P)] - c) for k in range(len(P)))
        L = np.linalg.norm(nv)
        if L < 1e-9: continue
        n = nv / L; u = np.cross(n, [1, 0, 0] if abs(n[0]) < 0.9 else [0, 1, 0]); u /= np.linalg.norm(u); w = np.cross(n, u)
        P2 = np.stack([(P - c) @ u, (P - c) @ w], 1)
        out.append((n, float(n @ c), c, u, w, P2))
    return out


def covered(pts2, P2, tol):
    x, y = pts2[:, 0:1], pts2[:, 1:2]
    a = P2; b = np.roll(P2, -1, 0)
    ax, ay, bx, by = a[:, 0][None], a[:, 1][None], b[:, 0][None], b[:, 1][None]
    cond = (ay > y) != (by > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = ax + (y - ay) * (bx - ax) / (by - ay)
    inside = (np.sum(cond & (x < xi), 1) % 2) == 1
    d = b - a; L2 = (d ** 2).sum(1)[None]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.clip(((x - ax) * d[:, 0][None] + (y - ay) * d[:, 1][None]) / np.where(L2 > 0, L2, 1), 0, 1)
    dist = np.sqrt((x - (ax + t * d[:, 0][None])) ** 2 + (y - (ay + t * d[:, 1][None])) ** 2).min(1)
    return inside | (dist <= tol)


def coverage(sid, sh):
    data = open(os.path.join(job, "subm", str(sid)), "rb").read()
    V, F = brep.parse(data)
    SF = stored_faces(np.asarray(V, float), F)
    C, A, N = tris(sh)
    if len(C) == 0:
        return dict(err="no triangles")
    ok = np.zeros(len(C), bool); tol = 0.003
    for n, d, c, u, w, P2 in SF:
        m = (~ok) & (np.abs(C @ n - d) <= tol) & (np.abs(N @ n) >= 0.98)
        if not m.any(): continue
        idx = np.where(m)[0]
        pts2 = np.stack([(C[idx] - c) @ u, (C[idx] - c) @ w], 1)
        ok[idx[covered(pts2, P2, tol)]] = True
    unc = float(A[~ok].sum()); tot = float(A.sum())
    r = dict(tri_area=round(tot, 4), uncovered_area=round(unc, 6), uncovered_frac=round(unc / tot, 7) if tot else None,
             n_tris=int(len(C)), n_uncovered=int((~ok).sum()), n_stored_faces=len(F))
    if (~ok).any():
        r["uncovered_examples"] = [[round(float(v), 4) for v in C[i]] + [round(float(A[i]), 5)] for i in np.where(~ok)[0][:8]]
    return r


base = json.load(open(basef))["pieces"] if basef else None
res = {}
for sid in sorted(cnt, key=lambda s: -cnt[s]):
    p = pieces[sid]; key = (job, sid)
    t1 = time.time()
    try:
        T2.brep_placed(job, sid, p, np.eye(3), np.zeros(3))
    except Exception as e:
        pass
    sh = T2._BREP.get(key)
    d = dict(name=p["name"], kind=kind(p), n_inst=cnt[sid], wt=round(float(p["wt"]), 4), L=round(float(p["L"]), 4),
             W=round(float(p["W"]), 4), T=round(float(p["T"]), 4), why=T2.BREP_WHY.get(key))
    for attr, nm in (("BREP_REPAIR", "repair"), ("BREP_WEIGHT_NOTE", "identity"), ("BREP_NEG_WEIGHT", "negwt"),
                     ("VALIDATED_BY_SECTION", "by_section"), ("OPEN_SURF", "open_surface"), ("UNVALIDATED", "unvalidated"),
                     ("CONCRETE", "concrete")):
        c_ = getattr(T2, attr, None)
        if c_ is not None and key in c_:
            d[nm] = c_[key] if isinstance(c_, dict) else True
    d["exact"] = sh is not None and not d.get("open_surface") and not d.get("unvalidated")
    if sh is not None:
        try:
            d.update(props(sh))
        except Exception as e:
            d["props_err"] = repr(e)
    if base is not None and d["exact"]:
        b = base.get(str(sid))
        if b is None or not b.get("exact"):
            try:
                d["coverage"] = coverage(sid, sh)
            except Exception as e:
                d["coverage"] = dict(err=repr(e))
    d["t"] = round(time.time() - t1, 3)
    res[str(sid)] = d

calib = []
if base is not None:
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    both = [s for s, d in res.items() if d["exact"] and base.get(s, {}).get("exact")][:15]
    for s in both:
        sh = T2._BREP.get((job, int(s)))
        try:
            c0 = coverage(int(s), sh)
            tr = gp_Trsf(); tr.SetTranslation(gp_Vec(0.05 * MM, 0.05 * MM, 0.05 * MM))
            c1 = coverage(int(s), BRepBuilderAPI_Transform(sh, tr, True).Shape())
            calib.append(dict(piece=s, name=res[s]["name"], same=c0.get("uncovered_frac"), shifted=c1.get("uncovered_frac")))
        except Exception as e:
            calib.append(dict(piece=s, err=repr(e)))
summ = dict(job=job, decode=DEC, pieces_n=len(res), placements=sum(cnt.values()),
            exact_pieces=sum(1 for d in res.values() if d["exact"]),
            exact_placements=sum(d["n_inst"] for d in res.values() if d["exact"]), wall=round(time.time() - t0, 1))
if base is not None:
    lost = [s for s, b in base.items() if b.get("exact") and not res.get(s, {}).get("exact")]
    new = [s for s, d in res.items() if d["exact"] and not base.get(s, {}).get("exact")]
    changed = [s for s, d in res.items() if d["exact"] and base.get(s, {}).get("exact") and
               (abs(d.get("vol", 0) - base[s].get("vol", 0)) > 1e-6 * max(1, base[s].get("vol", 0)) or
                d.get("nfaces") != base[s].get("nfaces"))]
    fab = [s for s in new if (res[s].get("coverage") or {}).get("uncovered_area", 1) > 1e-3 and
           (res[s].get("coverage") or {}).get("uncovered_frac", 1) > 1e-4]
    cov_err = [s for s in new if "err" in (res[s].get("coverage") or {"err": 1})]
    summ.update(lost_pieces=lost, lost_placements=sum(base[s]["n_inst"] for s in lost), changed_exact=changed,
                new_pieces=len(new), new_placements=sum(res[s]["n_inst"] for s in new), fabricated_suspects=fab,
                coverage_errors=cov_err, new_invalid=[s for s in new if res[s].get("valid") is False],
                new_by=dict(collections.Counter(("repair " if res[s].get("repair") else "") + ("identity " if res[s].get("identity") else "")
                                                 + ("negwt" if res[s].get("negwt") else "") or "other" for s in new)))
summ["calibration"] = calib
json.dump(dict(summary=summ, pieces=res), open(out, "w"), indent=0, default=str)
print(json.dumps(summ, default=str)[:3000])
