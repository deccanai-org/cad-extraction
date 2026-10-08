#!/usr/bin/env python3
"""Print the faces of a dumped solid (.brep) that BRepCheck flags, with their wires (vertex coords, signed area in the
face plane, outer/inner role) so the defect can be traced back to the source loop."""
import sys, collections
from OCC.Core.BRepTools import breptools, BRepTools_WireExplorer
from OCC.Core.BRep import BRep_Builder, BRep_Tool
from OCC.Core.TopoDS import TopoDS_Shape, topods
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_WIRE, TopAbs_REVERSED
from OCC.Core.BRepCheck import BRepCheck_Analyzer, BRepCheck_Status
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.ShapeAnalysis import shapeanalysis

ST = {getattr(BRepCheck_Status, n): n[10:] for n in dir(BRepCheck_Status) if n.startswith('BRepCheck_')}


def load(fn):
    s = TopoDS_Shape(); breptools.Read(s, fn, BRep_Builder()); return s


def wire_pts(w, f):
    ex = BRepTools_WireExplorer(w, f); pts = []
    while ex.More():
        v = ex.CurrentVertex(); p = BRep_Tool.Pnt(v); pts.append((round(p.X(), 3), round(p.Y(), 3), round(p.Z(), 3))); ex.Next()
    return pts


def main(fn, verbose=True):
    s = load(fn)
    an = BRepCheck_Analyzer(s)
    ex = TopExp_Explorer(s, TopAbs_FACE); k = 0
    while ex.More():
        f = topods.Face(ex.Current()); k += 1
        st = [ST.get(x) for x in an.Result(f).Status() if ST.get(x) != 'NoError']
        if st:
            surf = BRepAdaptor_Surface(f); pl = surf.Plane(); n = pl.Axis().Direction()
            print(f'face {k} {st} reversed={f.Orientation() == TopAbs_REVERSED} plane_n=({n.X():.3f},{n.Y():.3f},{n.Z():.3f})')
            ow = shapeanalysis.OuterWire(f)
            wx = TopExp_Explorer(f, TopAbs_WIRE)
            while wx.More():
                w = topods.Wire(wx.Current())
                pts = wire_pts(w, f)
                print('   wire', 'OUTER' if w.IsSame(ow) else 'inner', 'orient', w.Orientation(), len(pts), 'pts', pts[:12])
                wx.Next()
        ex.Next()


if __name__ == '__main__':
    for fn in sys.argv[1:]:
        print('==', fn); main(fn)
