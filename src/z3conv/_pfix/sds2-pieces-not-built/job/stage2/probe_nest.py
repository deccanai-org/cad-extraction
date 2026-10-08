import sys, os
sys.path.insert(0, sys.argv[1])
import numpy as np, brep
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.TopAbs import TopAbs_IN, TopAbs_SHELL, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Solid
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.ShapeFix import ShapeFix_Solid
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
MM = 25.4
W = '/work/agentwork/sds2-pieces-not-built/jobs/'
jn, sid = sys.argv[2].split(':')
V, F = brep.parse(open(os.path.join(W + jn, 'subm', sid), 'rb').read())
parts = brep.bodies(F)
out = [brep._solid(V, p) for p in parts]
def vol(s):
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(s, g); return g.Mass()
for i, s in enumerate(out):
    b = Bnd_Box(); BRepBndLib.Add_s(s, b); lo, hi = b.CornerMin(), b.CornerMax()
    print(i, 'signed vol', round(vol(s) / MM ** 3, 2), 'box', [round(x / MM, 3) for x in (lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z())])
ex = TopExp_Explorer(out[0], TopAbs_VERTEX)
st = []
while ex.More():
    q = BRep_Tool.Pnt_s(TopoDS.Vertex(ex.Current()))
    st.append(str(BRepClass3d_SolidClassifier(out[1], q, 1e-6).State()).split('.')[-1]); ex.Next()
print('inner verts in outer:', st)
r = brep._nest_voids(out)
print('nest result', len(r), [round(vol(s) / MM ** 3 * 0.2836, 2) for s in r])
