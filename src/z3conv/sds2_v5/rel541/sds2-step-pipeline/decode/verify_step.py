"""Independent check of a written STEP: read it back with OCC, count named solids, BRep-validate them, and (stage 1)
compare each member's cross-section area (volume / length) with its AISC weight (steel: 3.4 lb/ft per in^2).
Renders a shaded overview PNG from the tessellated STEP geometry.
usage: python verify_step.py <file.step> [members.csv] [out.png]
"""
import os, sys, csv, re, collections
import numpy as np
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCP.TopoDS import TopoDS
from OCP.BRep import BRep_Tool
from OCP.TopLoc import TopLoc_Location

MM = 25.4
LOAD_ERRORS = None


def product_names(path):
    """PRODUCT('name',...) entities in file order (one per written solid)."""
    rx = re.compile(r"=\s*PRODUCT\('([^']*)'")
    out = []
    with open(path, encoding="latin-1") as f:
        for line in f:
            m = rx.search(line)
            if m: out.append(m.group(1))
    return out


def load(path):
    """Top-level shapes in file order, paired with their PRODUCT names."""
    r = STEPControl_Reader()
    if r.ReadFile(path) != IFSelect_RetDone:
        raise SystemExit(f"cannot read {path}")
    global LOAD_ERRORS
    try:                                              # syntax / unresolved-reference failures (v4: NaN placements)
        import io
        from OCP.IFSelect import IFSelect_ListByItem
        buf = io.BytesIO(); r.PrintCheckLoad(buf, True, IFSelect_ListByItem)
        LOAD_ERRORS = sum(1 for l in buf.getvalue().decode(errors="replace").splitlines()
                          if "Check List : F:" in l and ("Parsing" in l or "Unresolved" in l))
    except Exception:
        LOAD_ERRORS = None
    r.TransferRoots()
    shapes = [r.Shape(i) for i in range(1, r.NbShapes() + 1)]
    names = product_names(path)
    if len(shapes) == 1 and len(names) > 1:           # everything came back as one compound: split it
        from OCP.TopoDS import TopoDS_Iterator
        it = TopoDS_Iterator(shapes[0]); shapes = []
        while it.More(): shapes.append(it.Value()); it.Next()
    if len(names) != len(shapes):
        # assembly (shared parts, one PRODUCT per unique piece): check every placed solid instead
        leaves = []
        from OCP.TopAbs import TopAbs_SHELL
        for s in shapes:
            ex = TopExp_Explorer(s, TopAbs_SOLID)
            while ex.More(): leaves.append(ex.Current()); ex.Next()
            ex = TopExp_Explorer(s, TopAbs_SHELL, TopAbs_SOLID)      # open reference surfaces (v5.2), not in a solid
            while ex.More(): leaves.append(ex.Current()); ex.Next()
        print(f"  assembly: {len(names)} products, {len(leaves)} placed solids")
        return [("", s) for s in leaves]
    return list(zip(names, shapes))


def tris(shape, defl=15.0):
    BRepMesh_IncrementalMesh(shape, defl, False, 0.5, True)
    out = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face(ex.Current()); loc = TopLoc_Location()
        t = BRep_Tool.Triangulation_s(f, loc)
        if t is not None:
            tr = loc.Transformation()
            P = np.array([[t.Node(k).Transformed(tr).X(), t.Node(k).Transformed(tr).Y(), t.Node(k).Transformed(tr).Z()]
                          for k in range(1, t.NbNodes() + 1)])
            for k in range(1, t.NbTriangles() + 1):
                a, b, c = t.Triangle(k).Get()
                out.append(P[[a - 1, b - 1, c - 1]])
        ex.Next()
    return out


RESULT = {}


def invalid_labels(path):
    """Names of the placed solids that are invalid after reading the STEP back (XCAF: component names + locations);
    verify's own pass only knows indices in assembly mode."""
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
    from OCP.TDF import TDF_Label
    from OCP.TDataStd import TDataStd_Name
    from OCP.TopLoc import TopLoc_Location
    try:
        from OCP.TDF import TDF_LabelSequence
    except ImportError:
        from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    rd = STEPCAFControl_Reader(); rd.SetNameMode(True)
    if rd.ReadFile(path) != IFSelect_RetDone:
        return []
    rd.Transfer(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    def nm(lab):
        a = TDataStd_Name()
        return a.Get().ToExtString() if lab.FindAttribute(TDataStd_Name.GetID_s(), a) else ""
    bad = []
    roots = TDF_LabelSequence(); st.GetFreeShapes(roots)
    for i in range(1, roots.Length() + 1):
        lab = roots.Value(i)
        if XCAFDoc_ShapeTool.IsAssembly_s(lab):
            comps = TDF_LabelSequence(); XCAFDoc_ShapeTool.GetComponents_s(lab, comps, False)
            for j in range(1, comps.Length() + 1):
                c = comps.Value(j); ref = TDF_Label(); XCAFDoc_ShapeTool.GetReferredShape_s(c, ref)
                shp = XCAFDoc_ShapeTool.GetShape_s(ref).Moved(XCAFDoc_ShapeTool.GetLocation_s(c))
                if not BRepCheck_Analyzer(shp).IsValid():
                    bad.append(nm(c) or nm(ref))
        elif not BRepCheck_Analyzer(XCAFDoc_ShapeTool.GetShape_s(lab)).IsValid():
            bad.append(nm(lab))
    return [b for b in bad if b]


def main():
    RESULT.clear()
    path = sys.argv[1]
    csvp = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].endswith(".csv") else None
    png = next((a for a in sys.argv[2:] if a.endswith(".png")), None)
    items = load(path)
    print(f"{path}: {len(items)} top-level shapes")
    n_solid = n_valid = 0; vols = {}; v_all = []; boxes = []; bad_names = []
    for name, sh in items:
        ex = TopExp_Explorer(sh, TopAbs_SOLID); ns = 0
        while ex.More(): ns += 1; ex.Next()
        n_solid += ns > 0
        v_ = BRepCheck_Analyzer(sh).IsValid(); n_valid += v_
        if not v_:
            print("  invalid after read-back:", name)
            bad_names.append(name)
        g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); v_all.append(g.Mass() / MM ** 3)
        vols.setdefault(name, v_all[-1])            # by name for the stage-1 area check (first instance)
        b = Bnd_Box(); BRepBndLib.Add_s(sh, b)
        lo, hi = b.CornerMin(), b.CornerMax(); boxes.append((lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z()))
    print(f"  with solids: {n_solid}; BRep valid: {n_valid}; non-positive volume: {sum(v <= 0 for v in v_all)}")
    if LOAD_ERRORS:
        print(f"  STEP load errors (syntax / unresolved references): {LOAD_ERRORS}")
    print(f"  total volume: {sum(abs(v) for v in v_all):.1f} in3 ({sum(abs(v) for v in v_all) * 0.2836 / 2000:.1f} t as steel)")
    B = np.array(boxes).reshape(-1, 6) / MM
    if not len(B):
        RESULT.update(top_level_shapes=0, solids=0, valid=0, invalid=0, invalid_names=[], load_errors=LOAD_ERRORS or 0, bbox_in=None)
        return RESULT
    print(f"  model bbox (in): min {B[:, :3].min(0).round(1)} max {B[:, 3:].max(0).round(1)}")
    RESULT.update(top_level_shapes=len(items), solids=n_solid, valid=n_valid, invalid=len(items) - n_valid,
                  invalid_names=bad_names[:200], load_errors=LOAD_ERRORS or 0,
                  bbox_in=[float(x) for x in list(B[:, :3].min(0).round(2)) + list(B[:, 3:].max(0).round(2))])
    if csvp:
        rows = {f"{r['type']} {r['section']} #{r['id']}": r for r in csv.DictReader(open(csvp)) if r["solid"] == "1"}
        ratio = collections.defaultdict(list)
        # weight per ft is encoded in the name for W/C/WT/M/S/HP (e.g. W18x35); HSS/L: skip
        for name, v in vols.items():
            r = rows.get(name)
            if not r: continue
            m = re.fullmatch(r"(W|M|S|HP|C|MC|WT|MT|ST)\d+(?:\.\d+)?x(\d+(?:\.\d+)?)", r["section"])
            if not m: continue
            L = np.linalg.norm(np.subtract([float(r["x2"]), float(r["y2"]), float(r["z2"])], [float(r["x1"]), float(r["y1"]), float(r["z1"])]))
            ratio[m.group(1)].append((v / L) / (float(m.group(2)) / 3.4))
        for f, v in sorted(ratio.items()):
            v = np.array(v)
            print(f"  area/AISC-area [{f}]: n={len(v)} median={np.median(v):.3f} p5={np.percentile(v, 5):.3f} p95={np.percentile(v, 95):.3f}")
    if png:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        c = np.median((B[:, :3] + B[:, 3:]) / 2, axis=0)
        keep = [i for i in range(len(items)) if np.linalg.norm(((B[i, :3] + B[i, 3:]) / 2 - c)[:2]) < 6000]
        # v5.4.1: tessellate at most PREVIEW_MAX solids (the largest by bbox diagonal). v5.4 meshed every solid into
        # Python lists of triangles, which dominated peak memory on big jobs (reference meshes, 200k+ bolts).
        PREVIEW_MAX = int(os.environ.get("SDS2_PREVIEW_MAX", "6000"))
        if len(keep) > PREVIEW_MAX:
            diag = np.linalg.norm(B[keep, 3:] - B[keep, :3], axis=1)
            keep = [keep[j] for j in np.argsort(-diag)[:PREVIEW_MAX]]
        T = []
        for i in keep: T += tris(items[i][1])
        T = np.array(T) / MM
        if not len(T):
            print("  preview skipped: nothing to draw near the model centre")
            return RESULT
        lo, hi = T.reshape(-1, 3).min(0), T.reshape(-1, 3).max(0); ctr = (lo + hi) / 2; R = (hi - lo).max() / 2
        fig = plt.figure(figsize=(13, 9), dpi=120); ax = fig.add_subplot(projection="3d")
        nrm = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
        lum = 0.35 + 0.65 * np.abs(nrm @ (np.array([0.4, -0.5, 0.77]) / 1.06))
        ax.add_collection3d(Poly3DCollection(T, facecolors=lum[:, None] * np.array([0.36, 0.52, 0.77]), linewidths=0))
        ax.set_xlim(ctr[0] - R, ctr[0] + R); ax.set_ylim(ctr[1] - R, ctr[1] + R); ax.set_zlim(ctr[2] - R / 3, ctr[2] + R / 3)
        ax.set_box_aspect((1, 1, 1 / 3)); ax.view_init(elev=28, azim=-60); ax.set_axis_off()
        ax.set_title(f"{os.path.basename(path)} - {len(items)} solids read back from STEP ({len(keep)} largest drawn)")
        plt.tight_layout(); plt.savefig(png); print("  saved", png, len(T), "triangles")
    return RESULT


if __name__ == "__main__":
    main()
