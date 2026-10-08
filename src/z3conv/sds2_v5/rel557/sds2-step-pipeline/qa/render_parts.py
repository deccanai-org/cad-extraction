"""Render the STEP solids whose names match a regex (read back with OCC XCAF) to a PNG.
usage: python render_parts.py <file.step> <name regex> <out.png> [max parts]"""
import sys, re
import numpy as np
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
from OCP.TDF import TDF_Label
from OCP.TDataStd import TDataStd_Name
try:
    from OCP.TDF import TDF_LabelSequence
except ImportError:
    from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
sys.path.insert(0, __file__.rsplit("/qa/", 1)[0] + "/decode")
from verify_step import tris

path, rx, png = sys.argv[1], re.compile(sys.argv[2]), sys.argv[3]
mx = int(sys.argv[4]) if len(sys.argv) > 4 else 40
doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
rd = STEPCAFControl_Reader(); rd.SetNameMode(True); rd.ReadFile(path); rd.Transfer(doc)
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())


def nm(lab):
    a = TDataStd_Name()
    return a.Get().ToExtString() if lab.FindAttribute(TDataStd_Name.GetID_s(), a) else ""


sel = []
roots = TDF_LabelSequence(); st.GetFreeShapes(roots)
for i in range(1, roots.Length() + 1):
    lab = roots.Value(i)
    if XCAFDoc_ShapeTool.IsAssembly_s(lab):
        comps = TDF_LabelSequence(); XCAFDoc_ShapeTool.GetComponents_s(lab, comps, False)
        for j in range(1, comps.Length() + 1):
            c = comps.Value(j); ref = TDF_Label(); XCAFDoc_ShapeTool.GetReferredShape_s(c, ref)
            if rx.search(nm(c)):
                sel.append((nm(c), XCAFDoc_ShapeTool.GetShape_s(ref).Moved(XCAFDoc_ShapeTool.GetLocation_s(c))))
    elif rx.search(nm(lab)):
        sel.append((nm(lab), XCAFDoc_ShapeTool.GetShape_s(lab)))
sel = sel[:mx]
T = []
for _, s in sel:
    T += tris(s, 2.0)
T = np.array(T) / 25.4
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
lo, hi = T.reshape(-1, 3).min(0), T.reshape(-1, 3).max(0); c = (lo + hi) / 2; R = (hi - lo).max() / 2
fig = plt.figure(figsize=(12, 8), dpi=110); ax = fig.add_subplot(projection="3d")
nrm = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]); nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
lum = 0.35 + 0.65 * np.abs(nrm @ (np.array([0.4, -0.5, 0.77]) / 1.06))
ax.add_collection3d(Poly3DCollection(T, facecolors=lum[:, None] * np.array([0.36, 0.52, 0.77]), linewidths=0))
ax.set_xlim(c[0] - R, c[0] + R); ax.set_ylim(c[1] - R, c[1] + R); ax.set_zlim(c[2] - R, c[2] + R)
ax.set_box_aspect((1, 1, 1)); ax.view_init(elev=22, azim=-55); ax.set_axis_off()
ax.set_title(f"{len(sel)} parts matching /{sys.argv[2]}/ (read back from STEP)\n{sel[0][0][:110] if sel else ''}", fontsize=8)
plt.tight_layout(); plt.savefig(png); print(png, len(sel), len(T))
