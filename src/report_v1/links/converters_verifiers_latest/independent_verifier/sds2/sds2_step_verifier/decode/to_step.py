"""SDS2 job folder -> STEP AP214 (one named solid per structural member), plus a members CSV.

Stage 1 geometry: straight prismatic members along the work line, exact AISC profile from job_mtrl,
roll from mem_idx. No cuts, copes, holes or connection material yet.

usage: python to_step.py <job_dir> <out.step> [--up-vertical X|Y] [--beam-tos 1|0]
Defaults (X, 1) validated on 50_Binney: 83% beams / 86% columns within 0.25in of the IFC cross-section bbox.
"""
import sys, os, csv, math, argparse
import numpy as np
from sds2job import read_members, read_version

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
STRUCTURAL = {"BEAM", "COLUMN", "VERTICAL BRACE", "HORIZONTAL BRACE", "PL GIRDER", "JOIST", "ANGLE", "KICKER", "EMBED", "MISC"}


def profile(sh):
    """2D outline (u = web/depth direction, v = flange direction) in inches, centred on the section's bbox centre.
    Returns list of loops (outer first); hollow shapes return 2 loops."""
    f, d, bf, tf, tw = sh.family, sh.d, sh.bf, sh.tf, sh.tw
    if d <= 0:
        return None
    if f in ("W", "M", "S", "HP", "WBX", "WPS", "PLG"):
        h, b = d / 2, bf / 2
        return [[(h, -b), (h, b), (h - tf, b), (h - tf, tw / 2), (-h + tf, tw / 2), (-h + tf, b), (-h, b), (-h, -b),
                 (-h + tf, -b), (-h + tf, -tw / 2), (h - tf, -tw / 2), (h - tf, -b)]]
    if f in ("C", "MC"):
        h = d / 2; b0, b1 = -bf / 2, bf / 2
        return [[(h, b0), (h, b1), (h - tf, b1), (h - tf, b0 + tw), (-h + tf, b0 + tw), (-h + tf, b1), (-h, b1), (-h, b0)]]
    if f in ("WT", "MT", "ST"):
        top = d / 2; b = bf / 2
        return [[(top, -b), (top, b), (top - tf, b), (top - tf, tw / 2), (-top, tw / 2), (-top, -tw / 2), (top - tf, -tw / 2), (top - tf, -b)]]
    if f == "L":
        t = tf if tf > 0 else tw
        a, c = d / 2, bf / 2
        return [[(a, -c), (a, -c + t), (-a + t, -c + t), (-a + t, c), (-a, c), (-a, -c)]]
    if f in ("HSS", "TS", "TB") and bf > 0:
        t = tf if tf > 0 else tw
        h, b = d / 2, bf / 2
        return [[(h, -b), (h, b), (-h, b), (-h, -b)], [(h - t, -b + t), (-h + t, -b + t), (-h + t, b - t), (h - t, b - t)]]
    if f in ("PIPE", "HS", "HSS") or bf <= 0:
        r = d / 2; t = tf if tf > 0 else tw
        n = 32
        outer = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]
        loops = [outer]
        if 0 < t < r:
            loops.append([((r - t) * math.cos(-2 * math.pi * i / n), (r - t) * math.sin(-2 * math.pi * i / n)) for i in range(n)])
        return loops
    # fallback: bounding rectangle
    h, b = d / 2, max(bf, tw, 0.25) / 2
    return [[(h, -b), (h, b), (-h, b), (-h, -b)]]


def frame(m, up_vertical):
    p1, p2 = np.array(m.p1), np.array(m.p2)
    x = p2 - p1
    L = np.linalg.norm(x)
    if L < 0.5:
        return None
    x /= L
    Z = np.array([0.0, 0.0, 1.0])
    ref = Z if abs(x @ Z) < 0.999 else (np.array([1.0, 0, 0]) if up_vertical == "X" else np.array([0, 1.0, 0]))
    u = ref - (ref @ x) * x; u /= np.linalg.norm(u)
    v = np.cross(x, u)
    c, s = math.cos(m.roll), math.sin(m.roll)
    u, v = c * u + s * v, -s * u + c * v
    return p1, x, u, v, L


def solid_for(m, up_vertical, beam_tos):
    if m.section is None:
        return None
    fr = frame(m, up_vertical)
    if fr is None:
        return None
    p1, x, u, v, L = fr
    loops = profile(m.section)
    if not loops:
        return None
    off = -m.section.d / 2 if (beam_tos and m.type in ("BEAM", "PL GIRDER") and abs(x[2]) < 0.999) else 0.0
    faces = None
    for i, loop in enumerate(loops):
        poly = BRepBuilderAPI_MakePolygon()
        for a, b in loop:
            q = p1 + u * (a + off) + v * b
            poly.Add(gp_Pnt(*(q * MM)))
        poly.Close()
        w = poly.Wire()
        if i == 0:
            faces = BRepBuilderAPI_MakeFace(w, True)
        else:
            w.Reverse()
            faces.Add(w)
    if not faces.IsDone():
        return None
    return BRepPrimAPI_MakePrism(faces.Face(), gp_Vec(*(x * L * MM))).Shape()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job"); ap.add_argument("out")
    ap.add_argument("--up-vertical", default="X")
    ap.add_argument("--beam-tos", type=int, default=1)
    a = ap.parse_args()
    mems, layout = read_members(a.job)
    print("layout", {k: (hex(v) if isinstance(v, int) else v) for k, v in layout.items()})
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    rows, n_ok = [], 0
    for m in mems:
        if m.type not in STRUCTURAL:
            continue
        try:
            sh = solid_for(m, a.up_vertical, a.beam_tos)
        except Exception:            # degenerate profile (e.g. zero dims from a mis-decoded section): skip, do not abort
            sh = None
        rows.append(dict(id=m.id, type=m.type, section=m.section.name if m.section else "", roll=round(m.roll, 4),
                         x1=m.p1[0], y1=m.p1[1], z1=m.p1[2], x2=m.p2[0], y2=m.p2[1], z2=m.p2[2], solid=int(sh is not None)))
        if sh is None:
            continue
        lab = st.AddShape(sh, False)
        TDataStd_Name.Set_s(lab, TCollection_ExtendedString(f"{m.type} {m.section.name} #{m.id}"))
        n_ok += 1
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    w = STEPCAFControl_Writer()
    w.SetNameMode(True)
    w.Transfer(doc, STEPControl_AsIs)
    ok = w.Write(a.out) == IFSelect_RetDone
    with open(os.path.splitext(a.out)[0] + "_members.csv", "w", newline="") as f:
        cw = csv.DictWriter(f, fieldnames=list(rows[0].keys())); cw.writeheader(); cw.writerows(rows)
    print(f"version {read_version(a.job)}; members {len(mems)}; structural {len(rows)}; solids {n_ok}; write ok={ok} -> {a.out}")


if __name__ == "__main__":
    main()


