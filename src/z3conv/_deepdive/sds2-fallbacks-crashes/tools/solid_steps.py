"""Step through brep._solid for one piece file: sewing, shells, MakeSolid, ShapeFix, BRepCheck (which check fails)."""
import sys, numpy as np
sys.path.insert(0, sys.argv[1])
import brep
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid
from OCP.gp import gp_Pnt
from OCP.TopoDS import TopoDS
from OCP.TopAbs import TopAbs_SHELL, TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.ShapeFix import ShapeFix_Solid, ShapeFix_Face, ShapeFix_Shape
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
MM = 25.4
for path in sys.argv[2:]:
    V, F = brep.parse(open(path, 'rb').read()); W = V
    sew = BRepBuilderAPI_Sewing(1e-3 * MM); n = 0; badface = 0
    for f in F:
        ls = brep.loops_of(f); ls.sort(key=lambda l: -brep._area(W[l]))
        def wire(idx):
            p = BRepBuilderAPI_MakePolygon()
            for i in idx: p.Add(gp_Pnt(*(W[i] * MM)))
            p.Close(); return p.Wire() if p.IsDone() else None
        mf = BRepBuilderAPI_MakeFace(wire(ls[0]), True)
        if not mf.IsDone(): badface += 1; continue
        for l in ls[1:]: mf.Add(wire(l))
        face = mf.Face()
        if len(ls) > 1:
            fx = ShapeFix_Face(face); fx.FixOrientation(); fx.Perform(); face = fx.Face()
            print('  multi-loop face valid after FixOrientation:', BRepCheck_Analyzer(face).IsValid(), [len(l) for l in ls])
        sew.Add(face); n += 1
    sew.Perform()
    print(path, 'faces added', n, 'MakeFace failed', badface, 'free', sew.NbFreeEdges())
    ex = TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL); k = 0
    while ex.More():
        k += 1
        ms = BRepBuilderAPI_MakeSolid(TopoDS.Shell(ex.Current()))
        print('  shell', k, 'MakeSolid done', ms.IsDone())
        if ms.IsDone():
            s = ms.Solid(); print('   raw solid valid', BRepCheck_Analyzer(s).IsValid())
            fx = ShapeFix_Solid(s); fx.Perform(); s2 = fx.Solid()
            g = GProp_GProps(); BRepGProp.VolumeProperties_s(s2, g)
            print('   ShapeFix_Solid valid', BRepCheck_Analyzer(s2).IsValid(), 'volume in3', round(g.Mass() / MM ** 3, 3))
            if not BRepCheck_Analyzer(s2).IsValid():
                fs = ShapeFix_Shape(s2); fs.Perform(); s3 = fs.Shape()
                print('   ShapeFix_Shape valid', BRepCheck_Analyzer(s3).IsValid())
                # which faces are invalid
                fe = TopExp_Explorer(s2, TopAbs_FACE); nb = 0; tot = 0
                while fe.More():
                    tot += 1
                    if not BRepCheck_Analyzer(fe.Current()).IsValid(): nb += 1
                    fe.Next()
                print('   invalid faces', nb, 'of', tot)
        ex.Next()
