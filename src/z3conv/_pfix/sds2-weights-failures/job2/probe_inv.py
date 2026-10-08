"""Read a stage-2 STEP (XCAF), find components invalid after read-back, and say why + whether a fix keeps them valid."""
import sys, collections, os, tempfile
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
from OCP.TDF import TDF_Label
try:
    from OCP.TDF import TDF_LabelSequence
except ImportError:
    from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
from OCP.TDataStd import TDataStd_Name
from OCP.IFSelect import IFSelect_RetDone
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_SOLID, TopAbs_SHELL, TopAbs_VERTEX, TopAbs_WIRE
from OCP.BRep import BRep_Tool
from OCP.ShapeFix import ShapeFix_Shape
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
path = sys.argv[1]; want = int(sys.argv[2]) if len(sys.argv) > 2 else 6
doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
rd = STEPCAFControl_Reader(); rd.SetNameMode(True)
assert rd.ReadFile(path) == IFSelect_RetDone
rd.Transfer(doc)
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
def nm(lab):
    a = TDataStd_Name()
    return a.Get().ToExtString() if lab.FindAttribute(TDataStd_Name.GetID_s(), a) else ""
roots = TDF_LabelSequence(); st.GetFreeShapes(roots)
bad = []
flat_bad = 0; comp_bad = 0
for i in range(1, roots.Length() + 1):
    lab = roots.Value(i)
    if XCAFDoc_ShapeTool.IsAssembly_s(lab):
        comps = TDF_LabelSequence(); XCAFDoc_ShapeTool.GetComponents_s(lab, comps, False)
        for j in range(1, comps.Length() + 1):
            c = comps.Value(j); ref = TDF_Label(); XCAFDoc_ShapeTool.GetReferredShape_s(c, ref)
            loc = XCAFDoc_ShapeTool.GetLocation_s(c)
            shp = XCAFDoc_ShapeTool.GetShape_s(ref).Moved(loc)
            if not BRepCheck_Analyzer(shp).IsValid():
                comp_bad += 1; bad.append(("comp", nm(c) or nm(ref), shp, XCAFDoc_ShapeTool.GetShape_s(ref)))
    else:
        shp = XCAFDoc_ShapeTool.GetShape_s(lab)
        if not BRepCheck_Analyzer(shp).IsValid():
            flat_bad += 1; bad.append(("flat", nm(lab), shp, None))
print("invalid: components", comp_bad, "flat", flat_bad)
print(collections.Counter(b[1].split(" (piece")[0].split(" / ")[-1] for b in bad).most_common(10))
def why(shp):
    out = collections.Counter()
    for T, tn in ((TopAbs_VERTEX, "V"), (TopAbs_EDGE, "E"), (TopAbs_WIRE, "W"), (TopAbs_FACE, "F"), (TopAbs_SHELL, "Sh"), (TopAbs_SOLID, "So")):
        ex = TopExp_Explorer(shp, T)
        while ex.More():
            out[tn + "_n"] += 1
            if not BRepCheck_Analyzer(ex.Current()).IsValid():
                out[tn + "_bad"] += 1
            ex.Next()
    from OCP.ShapeAnalysis import ShapeAnalysis_ShapeTolerance
    tl = ShapeAnalysis_ShapeTolerance()
    out["maxtol_mm"] = round(tl.Tolerance(shp, 1), 5)
    return out
def nfaces(s):
    ex = TopExp_Explorer(s, TopAbs_FACE); n = 0
    while ex.More(): n += 1; ex.Next()
    return n
def vol(s):
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(s, g); return g.Mass()
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs, STEPControl_Reader
def roundtrip(s):
    f = tempfile.mktemp(suffix=".step"); w = STEPControl_Writer(); w.Transfer(s, STEPControl_AsIs); w.Write(f)
    r = STEPControl_Reader(); r.ReadFile(f); r.TransferRoots(); x = r.OneShape(); os.remove(f); return x
seen = set()
for kind, name, shp, local in bad:
    key = name.split(", inst")[0].split(" / ")[-1]
    if key in seen: continue
    seen.add(key)
    if len(seen) > want: break
    print("==", kind, name, "faces", nfaces(shp), "vol", round(vol(shp)))
    print("   why:", dict(why(shp)))
    if local is not None:
        print("   local valid:", BRepCheck_Analyzer(local).IsValid())
    fx = ShapeFix_Shape(shp); fx.Perform(); f2 = fx.Shape()
    ok = BRepCheck_Analyzer(f2).IsValid()
    print("   ShapeFix valid:", ok, "vol", round(vol(f2)), "faces", nfaces(f2), "-> roundtrip valid:", BRepCheck_Analyzer(roundtrip(f2)).IsValid() if ok else None)
