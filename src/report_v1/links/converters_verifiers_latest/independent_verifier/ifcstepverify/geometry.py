"""Geometry, per part (STEP, OpenCascade) and per element (IFC, IfcOpenShell). Deterministic: every part is
checked; above BREPCHECK_ALL_MAX parts, BRepCheck runs on every k-th part (fixed stride, no randomness)."""
import os
import numpy as np
from . import config as C


def analyze_step(path):
    """-> dict(parts=[...], summary) or dict(error=...). OpenCascade converts every file to millimetres on read."""
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepCheck import BRepCheck_Analyzer
    rd = STEPControl_Reader()
    if rd.ReadFile(path) != IFSelect_RetDone:
        return dict(error="OpenCascade could not read the file")
    nr = rd.NbRootsForTransfer()
    stride = 1 if nr <= C.BREPCHECK_ALL_MAX else -(-nr // C.BREPCHECK_ALL_MAX)
    parts = []
    def count(s, t):
        e = TopExp_Explorer(s, t); n = 0
        while e.More(): n += 1; e.Next()
        return n
    for i in range(1, nr + 1):
        rd.ClearShapes(); rd.TransferRoot(i); s = rd.OneShape()
        p = dict(part=i)
        if s.IsNull(): p["kind"] = "empty"; parts.append(p); continue
        b = Bnd_Box(); BRepBndLib.AddOptimal_s(s, b, False, False)
        if b.IsVoid(): p["kind"] = "empty"; parts.append(p); continue
        mn, mx = b.CornerMin(), b.CornerMax()
        p["bbox"] = [mn.X(), mn.Y(), mn.Z(), mx.X(), mx.Y(), mx.Z()]
        box = max(0.0, (mx.X() - mn.X())) * max(0.0, (mx.Y() - mn.Y())) * max(0.0, (mx.Z() - mn.Z()))
        ns = count(s, TopAbs_SOLID)
        p["solids"] = ns; p["faces"] = count(s, TopAbs_FACE)
        if ns == 0:
            p["kind"] = "open_shell"
        else:
            g = GProp_GProps(); BRepGProp.VolumeProperties_s(s, g); v = abs(g.Mass())
            p["volume_mm3"] = v; p["box_mm3"] = box
            p["kind"] = "impossible_solid" if v > box * C.VOLUME_BOX_FACTOR + 1e-6 else "solid"
            if (i - 1) % stride == 0: p["brep_valid"] = bool(BRepCheck_Analyzer(s).IsValid())
        parts.append(p)
    lo = np.array([min((p["bbox"][k] for p in parts if "bbox" in p), default=0) for k in range(3)])
    hi = np.array([max((p["bbox"][k + 3] for p in parts if "bbox" in p), default=0) for k in range(3)])
    kinds = {k: sum(p["kind"] == k for p in parts) for k in ("solid", "impossible_solid", "open_shell", "empty")}
    checked = [p for p in parts if "brep_valid" in p]
    vol = sorted(p["volume_mm3"] for p in parts if p["kind"] == "solid")
    return dict(parts=parts, summary=dict(parts=nr, **kinds, brepcheck_checked=len(checked), brepcheck_stride=stride,
                                          brepcheck_invalid=sum(not p["brep_valid"] for p in checked),
                                          bbox_dims_mm=[float(x) for x in (hi - lo)], volume_m3_clean=float(sum(vol)) / 1e9))


def analyze_ifc(ifc_file, threads=None):
    """Mesh every physical element. -> {GlobalId: dict(type, name, volume_m3, bbox_m, centre_mm, impossible)} + summary."""
    import ifcopenshell.geom
    st = ifcopenshell.geom.settings(); st.set("use-world-coords", True)
    it = ifcopenshell.geom.iterator(st, ifc_file, threads or os.cpu_count() or 4)
    out = {}
    if it.initialize():
        while True:
            sh = it.get()
            if sh.type not in C.NONPHYS:
                v = np.array(sh.geometry.verts).reshape(-1, 3); fc = np.array(sh.geometry.faces).reshape(-1, 3)
                if len(v):
                    vol = abs(float(np.einsum("ij,ij->i", v[fc[:, 0]], np.cross(v[fc[:, 1]], v[fc[:, 2]])).sum()) / 6) if len(fc) else 0.0
                    lo, hi = v.min(0), v.max(0)
                    out[sh.guid] = dict(type=sh.type, name=sh.name, volume_m3=vol, bbox_m=[*map(float, lo), *map(float, hi)],
                                        centre_mm=[float(x) * 1000 for x in (lo + hi) / 2],
                                        impossible=vol > float(np.prod(hi - lo)) * C.VOLUME_BOX_FACTOR + 1e-12)
            if not it.next(): break
    good = sorted(e["volume_m3"] for e in out.values() if not e["impossible"])
    if out:
        lo = np.min([e["bbox_m"][:3] for e in out.values()], axis=0); hi = np.max([e["bbox_m"][3:] for e in out.values()], axis=0)
        dims = [float(x) for x in (hi - lo)]
    else:
        dims = [0.0, 0.0, 0.0]
    return out, dict(elements_meshed=len(out), impossible_elements=sum(e["impossible"] for e in out.values()),
                     bbox_dims_m=dims, volume_m3_clean=float(sum(good)))
