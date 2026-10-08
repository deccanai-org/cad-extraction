"""Stage 2: SDS2 job -> STEP with fabricated pieces (main material + connection plates/angles), 7.243 layout.

Each placed piece (mem material block: rotation M, global origin o, piece id) becomes a solid:
  plate  : 2D convex hull of its vertices in the plate plane (thinnest bbox axis), extruded over the thickness
  rolled : AISC profile from job_mtrl, extruded along local x over the vertex x-range; profile orientation
           (4 sign flips) chosen so the most vertices lie on the profile boundary; fitted to the vertex y/z bbox
World point = o + M.T @ local  (validated on 50_Binney: plates 78% within 1in of the IFC part).
No holes, copes or cuts yet (needs subm topology).
usage: python to_step2.py <job_dir> <out.step>
"""
import os, sys, csv, math
import numpy as np
from scipy.spatial import ConvexHull
from instances import material_instances, subm_vertices
from piece_table import read_pieces, kind
from sds2job import read_shapes, read_version, read_members
import to_step as T

from OCP.gp import gp_Pnt, gp_Vec
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDataStd import TDataStd_Name
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.Interface import Interface_Static
from OCP.IFSelect import IFSelect_RetDone

MM = 25.4


def prism(loop_world, extrude_world):
    poly = BRepBuilderAPI_MakePolygon()
    for q in loop_world:
        poly.Add(gp_Pnt(*(q * MM)))
    poly.Close()
    f = BRepBuilderAPI_MakeFace(poly.Wire(), True)
    if not f.IsDone():
        return None
    return BRepPrimAPI_MakePrism(f.Face(), gp_Vec(*(extrude_world * MM))).Shape()


def plate_local(V):
    """Returns (loop in local coords, extrusion vector local) for a plate from its vertices."""
    ext = V.max(0) - V.min(0)
    t = int(np.argmin(ext))
    a, b = [i for i in range(3) if i != t]
    pts2 = V[:, [a, b]]
    try:
        hull = ConvexHull(pts2)
        ring = pts2[hull.vertices]
    except Exception:
        lo, hi = pts2.min(0), pts2.max(0)
        ring = np.array([lo, [hi[0], lo[1]], hi, [lo[0], hi[1]]])
    loop = []
    for p in ring:
        q = np.zeros(3); q[a], q[b], q[t] = p[0], p[1], V[:, t].min(); loop.append(q)
    e = np.zeros(3); e[t] = ext[t]
    return loop, e


def rolled_local(V, sh):
    """Profile loop in local (y,z) at x = xmin, extrusion along local x."""
    loops = T.profile(sh)
    if not loops:
        return None
    outer = np.array(loops[0])                     # (u = depth dir, v = flange dir), centred
    lo, hi = V.min(0), V.max(0)
    cy, cz = (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2
    best = None
    for su in (1, -1):
        for sv in (1, -1):
            P = np.c_[outer[:, 0] * su + cy, outer[:, 1] * sv + cz]
            # score: vertices lying on the profile boundary (distance to nearest edge < 0.02)
            seg_a, seg_b = P, np.roll(P, -1, axis=0)
            yz = V[:, 1:]
            d = np.full(len(yz), 1e9)
            for A, Bp in zip(seg_a, seg_b):
                AB = Bp - A; L2 = AB @ AB
                if L2 == 0: continue
                tt = np.clip(((yz - A) @ AB) / L2, 0, 1)
                d = np.minimum(d, np.linalg.norm(yz - (A + np.outer(tt, AB)), axis=1))
            sc = np.sum(d < 0.02)
            if best is None or sc > best[0]:
                best = (sc, P)
    P = best[1]
    loop = [np.array([lo[0], y, z]) for y, z in P]
    return loop, np.array([hi[0] - lo[0], 0, 0])


def main():
    job, out = sys.argv[1], sys.argv[2]
    pieces = read_pieces(job); shapes = read_shapes(job)
    mems, _ = read_members(job)
    mtype = {m.id: m.type for m in mems}
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    rows = []; stats = {"plate": 0, "rolled": 0, "skipped": 0}
    for n in sorted(mtype):
        if mtype[n] == "Ref Point":
            continue
        for sid, M, o in material_instances(job, n, pieces)[1]:
            p = pieces[sid]; k = kind(p)
            V = subm_vertices(job, sid)
            if V is None or len(V) < 4:
                stats["skipped"] += 1; continue
            if k == "plate":
                loc = plate_local(V)
            elif k == "rolled" and p["sec"] in shapes:
                loc = rolled_local(V, shapes[p["sec"]])
            else:
                loc = None
            if loc is None:
                stats["skipped"] += 1; continue
            loop, e = loc
            Rt = M.T
            try:
                sh = prism([o + Rt @ q for q in loop], Rt @ e)
            except Exception:        # degenerate outline: skip this piece, do not abort the job
                sh = None
            if sh is None:
                stats["skipped"] += 1; continue
            lab = st.AddShape(sh, False)
            TDataStd_Name.Set_s(lab, TCollection_ExtendedString(f"{mtype[n]} #{n} / {p['name']} (piece {sid})"))
            stats[k] += 1
            rows.append(dict(member=n, member_type=mtype[n], piece=sid, name=p["name"], kind=k,
                             ox=round(o[0], 4), oy=round(o[1], 4), oz=round(o[2], 4)))
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    w = STEPCAFControl_Writer(); w.SetNameMode(True)
    w.Transfer(doc, STEPControl_AsIs)
    ok = w.Write(out) == IFSelect_RetDone
    with open(os.path.splitext(out)[0] + "_pieces.csv", "w", newline="") as f:
        cw = csv.DictWriter(f, fieldnames=list(rows[0].keys())); cw.writeheader(); cw.writerows(rows)
    print(f"version {read_version(job)}; solids: {stats}; write ok={ok} -> {out}")


if __name__ == "__main__":
    main()
