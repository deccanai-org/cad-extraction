"""SDS2 job folder -> STEP AP214 (one named solid per structural member), plus a members CSV.

Stage 1 geometry: straight prismatic members along the work line, exact AISC profile from job_mtrl,
roll from mem_idx. No cuts, copes, holes or connection material yet.

usage: python to_step.py <job_dir> <out.step> [--up-vertical X|Y] [--beam-tos 1|0]
Defaults (X, 1) validated on 50_Binney: 83% beams / 86% columns within 0.25in of the IFC cross-section bbox.
"""
import sys, os, csv, math, argparse, re
import numpy as np
from sds2job import read_members, read_version

from OCP.gp import gp_Pnt, gp_Vec
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.ShapeFix import ShapeFix_Face
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

PROFILE_NOTES = {}    # section name -> why its profile is approximate (built-up sections without usable dimensions)


def _builtup_loops(f, d, tw, bt, tt, bb, tb):
    h, wt, wb = d / 2, bt / 2, bb / 2
    if f == "WBX":
        return [[(h, -wt), (h, wt), (-h, wb), (-h, -wb)],
                [(h - tt, -wt + tw), (-h + tb, -wb + tw), (-h + tb, wb - tw), (h - tt, wt - tw)]]
    return [[(h, -wt), (h, wt), (h - tt, wt), (h - tt, tw / 2),
             (-h + tb, tw / 2), (-h + tb, wb), (-h, wb), (-h, -wb),
             (-h + tb, -wb), (-h + tb, -tw / 2), (h - tt, -tw / 2), (h - tt, -wt)]]


def _builtup_area(f, d, tw, bt, tt, bb, tb):
    return bt * tt + bb * tb + (d - tt - tb) * tw * (2 if f == "WBX" else 1)


def _builtup(sh):
    """PLG / WPS / WBX outline -> (loops, note). note is None when the dimensions are SDS2's own (record fields
    +0x5A.. reproduce the recorded weight within 2%, or the PLG name states them); otherwise a reason string and an
    approximate outline. v4 raised ValueError here, which aborted the whole job (7.1xx fixed records and 7.4 records
    without the extra fields have no bf_top..)."""
    f, d, tw, wt = sh.family, sh.d, sh.tw, sh.weight
    rec = (sh.bf_top, sh.tf_top, sh.bf_bot, sh.tf_bot)
    ok = lambda v: v is not None and math.isfinite(v) and v > 0
    named = re.fullmatch(r"PLG([\d.]+)x([\d.]+)/([\d.]+)/([\d.]+)", sh.name)
    if all(ok(v) for v in rec) and ok(tw) and ok(d):
        bt, tt, bb, tb = rec
        sane = d - tt - tb > 0 and bt >= tw and bb >= tw and not (f == "WBX" and (bt <= 2 * tw or bb <= 2 * tw))
        if sane:
            ratio = _builtup_area(f, d, tw, bt, tt, bb, tb) * 12 * 0.2836 / wt if ok(wt) else None
            name_ok = bool(named and all(math.isclose(a, float(e), abs_tol=1e-5) for a, e in zip((d, bt, tw, tt), named.groups()))
                           and math.isclose(bt, bb, abs_tol=1e-5) and math.isclose(tt, tb, abs_tol=1e-5))
            if name_ok or (ratio is not None and 0.98 <= ratio <= 1.02):
                return _builtup_loops(f, d, tw, bt, tt, bb, tb), None
    if named:
        dd, bf, w_, tf = (float(x) for x in named.groups())
        if dd - 2 * tf > 0 and bf >= w_:
            return _builtup_loops("PLG", dd, w_, bf, tf, bf, tf), None   # SDS2's section name states every dimension
    if ok(d) and ok(tw) and ok(wt):
        # dimensions unavailable: equal flanges sized from the recorded weight (bf = record bf when it is not the
        # 1.0 placeholder, else d / 2.5), web = tw
        A = wt / (12 * 0.2836)
        bf = sh.bf if ok(sh.bf) and sh.bf > 1.0 + 1e-6 else max(d / 2.5, 4 * tw)
        webs = 2 if f == "WBX" else 1
        tf = (A - d * tw * webs) / (2 * bf - 2 * tw * webs) if 2 * bf > 2 * tw * webs else 0
        if 0 < tf < d / 4:
            return _builtup_loops(f, d, tw, bf, tf, bf, tf), "built-up flanges estimated from the recorded weight"
    h, b = d / 2, max(sh.bf, tw, 0.25) / 2
    return [[(h, -b), (h, b), (-h, b), (-h, -b)]], "built-up section without usable dimensions: bounding rectangle"


def profile(sh):
    """2D outline (u = web/depth direction, v = flange direction) in inches, centred on the section's bbox centre.
    Returns list of loops (outer first); hollow shapes return 2 loops."""
    f, d, bf, tf, tw = sh.family, sh.d, sh.bf, sh.tf, sh.tw
    if d <= 0:
        return None
    if f in ("PLG", "WPS", "WBX"):
        loops, note = _builtup(sh)
        if note:
            PROFILE_NOTES[sh.name] = note
        return loops
    if f in ("W", "M", "S", "HP"):
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
    round_hss = f == "HSS" and sh.name.lower().count("x") == 1      # HSS10.750x0.500 (7.4 stores bf = d for these)
    if f in ("HSS", "TS", "TB") and bf > 0 and not round_hss:
        t = tf if tf > 0 else tw
        h, b = d / 2, bf / 2
        return [[(h, -b), (h, b), (-h, b), (-h, -b)], [(h - t, -b + t), (-h + t, -b + t), (-h + t, b - t), (h - t, b - t)]]
    if f in ("PIPE", "HS") or round_hss or bf <= 0:
        r = d / 2; t = tf if tf > 0 else tw
        n = 32
        if round_hss:
            # Many 7.2xx job_mtrl records store the *design* wall (0.93 of
            # nominal) while their own weight is based on the nominal gauge.
            # Pick the wall independently supported by the recorded weight;
            # leave PIPE and atypical HSS records unchanged.
            named = re.fullmatch(r"HSS([\d.]+)x([\d.]+)", sh.name)
            if named and sh.weight > 0:
                nominal = float(named.group(2))
                area = lambda wall: n * math.sin(2 * math.pi / n) / 2 * (r * r - (r - wall) ** 2)
                if 0 < nominal < r and 0 < t < r:
                    actual_err = abs(area(t) * 3.4032 / sh.weight - 1)
                    nominal_err = abs(area(nominal) * 3.4032 / sh.weight - 1)
                    if nominal_err < min(actual_err, 0.05):
                        t = nominal
        outer = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]
        loops = [outer]
        if 0 < t < r:
            loops.append([((r - t) * math.cos(-2 * math.pi * i / n), (r - t) * math.sin(-2 * math.pi * i / n)) for i in range(n)])
        return loops
    # fallback: bounding rectangle
    h, b = d / 2, max(bf, tw, 0.25) / 2
    return [[(h, -b), (h, b), (-h, b), (-h, -b)]]


def frame(m, up_vertical):
    p1, p2 = np.array(m.p1, float), np.array(m.p2, float)
    # garbage end points (overflowed doubles in damaged mem_idx slots) made OCC dump core on a NaN prism vector
    # (data-4 ANUSHA_JOB / AMOL_Job 7.135, v4 "other" failures): no solid for such members
    if not (np.isfinite(p1).all() and np.isfinite(p2).all()) or max(np.abs(p1).max(), np.abs(p2).max()) > 1e7:
        return None
    with np.errstate(all="ignore"):
        x = p2 - p1
        L = np.linalg.norm(x)
    if not np.isfinite(L) or L < 0.5 or L > 1e6:
        return None
    if not np.isfinite(m.roll):
        return None
    x /= L
    Z = np.array([0.0, 0.0, 1.0])
    ref = Z if abs(x @ Z) < 0.999 else (np.array([1.0, 0, 0]) if up_vertical == "X" else np.array([0, 1.0, 0]))
    u = ref - (ref @ x) * x; u /= np.linalg.norm(u)
    v = np.cross(x, u)
    c, s = math.cos(m.roll), math.sin(m.roll)
    u, v = c * u + s * v, -s * u + c * v
    return p1, x, u, v, L


ROLLED_FAMILIES = {"W", "M", "S", "HP", "HSS", "TS", "TB", "C", "MC", "L", "WT", "MT", "ST", "PIPE", "PLG", "WBX", "WPS"}


def is_joist(m):
    """Open-web joist member whose section is a designation, not a rolled shape (24K6, 32LH10, 64DLH12)."""
    import joist as J
    if m.section is None:
        return False
    if m.section.family in ROLLED_FAMILIES and not J.is_joist_section(m.section.name):
        return False
    return m.type == "JOIST" or J.is_joist_section(m.section.name)


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
    # work line = top of steel for beams, and top chord for joists (7.425: joist ends sit 2.5in / 5in seat above the
    # supporting beam's TOS), so hang the section below it
    off = -m.section.d / 2 if (beam_tos and m.type in ("BEAM", "PL GIRDER", "JOIST") and abs(x[2]) < 0.999) else 0.0
    faces = None
    try:                                           # degenerate profiles (zero-size sections) -> no solid, not a crash
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
                faces.Add(w)
        if faces is None or not faces.IsDone():
            return None
        face = faces.Face()
        if len(loops) > 1:
            fix = ShapeFix_Face(face); fix.FixOrientation(); face = fix.Face()
        return BRepPrimAPI_MakePrism(face, gp_Vec(*(x * L * MM))).Shape()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job"); ap.add_argument("out")
    ap.add_argument("--up-vertical", default="X")
    ap.add_argument("--beam-tos", type=int, default=1)
    a = ap.parse_args()
    convert(a.job, a.out, a.up_vertical, a.beam_tos)


def convert(job, out, up_vertical="X", beam_tos=1):
    mems, layout = read_members(job)
    print("layout", {k: hex(v) for k, v in layout.items()})
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    import joist as J
    rows, n_ok = [], 0
    for m in mems:
        if m.type not in STRUCTURAL:
            continue
        note = ""
        if is_joist(m):
            # open-web joist stand-in instead of a solid d x 6 in block (FIX item 1)
            wt, basis = J.typical_weight(m.section.name, m.section.d, m.section.weight)
            sh, info = J.joist_solid(m, wt)
            if sh is not None:
                note = f"derived_from_designation open-web joist, {wt:g} lb/ft ({basis})"
            else:
                sh = solid_for(m, up_vertical, beam_tos); note = "joist envelope box (no chord data)"
        else:
            sh = solid_for(m, up_vertical, beam_tos)
            if sh is not None and m.section.name in PROFILE_NOTES:
                note = PROFILE_NOTES[m.section.name]
        rows.append(dict(id=m.id, type=m.type, section=m.section.name if m.section else "", roll=round(m.roll, 4),
                         x1=m.p1[0], y1=m.p1[1], z1=m.p1[2], x2=m.p2[0], y2=m.p2[1], z2=m.p2[2], solid=int(sh is not None),
                         standin=note))
        if sh is None:
            continue
        lab = st.AddShape(sh, False)
        TDataStd_Name.Set_s(lab, TCollection_ExtendedString(f"{m.type} {m.section.name} #{m.id}" + (f" [approx: {note}]" if note else "")))
        n_ok += 1
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    w = STEPCAFControl_Writer()
    w.SetNameMode(True)
    w.Transfer(doc, STEPControl_AsIs)
    ok = w.Write(out) == IFSelect_RetDone
    with open(os.path.splitext(out)[0] + "_members.csv", "w", newline="") as f:
        # no structural members (seed / empty jobs): header only (v4 raised IndexError on rows[0])
        cw = csv.DictWriter(f, fieldnames=("id", "type", "section", "roll", "x1", "y1", "z1", "x2", "y2", "z2", "solid", "standin"))
        cw.writeheader(); cw.writerows(rows)
    print(f"version {read_version(job)}; members {len(mems)}; structural {len(rows)}; solids {n_ok}; write ok={ok} -> {out}")
    return ok, n_ok


if __name__ == "__main__":
    main()
