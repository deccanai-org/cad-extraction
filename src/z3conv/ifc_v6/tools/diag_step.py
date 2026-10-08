#!/usr/bin/env python3
"""per-solid diagnosis of a STEP (OCC): volume, BRepCheck status codes, shells, free edges. usage: diag_step.py FILE [--all] [--max N]"""
import sys, collections
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TopExp import TopExp_Explorer, topexp
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE, TopAbs_EDGE
from OCC.Core.BRepCheck import BRepCheck_Analyzer, BRepCheck_ListOfStatus
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
from OCC.Core.ShapeAnalysis import ShapeAnalysis_FreeBounds
from OCC.Core.TopoDS import topods
args = [x for x in sys.argv[1:] if not x.startswith('--')]
ALL = '--all' in sys.argv
r = STEPControl_Reader(); r.ReadFile(args[0])
model = r.WS().Model()
n = r.NbRootsForTransfer()
stat = collections.Counter(); shown = 0
for i in range(1, n + 1):
    r.TransferRoot(i); sh = r.Shape(r.NbShapes())
    ent = r.RootForTransfer(i); lab = model.StringLabel(ent).ToCString()
    ex = TopExp_Explorer(sh, TopAbs_SOLID); k = 0
    while ex.More():
        s = ex.Current(); ex.Next(); k += 1
        g = GProp_GProps(); brepgprop.VolumeProperties(s, g); v = g.Mass()
        an = BRepCheck_Analyzer(s); ok = an.IsValid()
        nsh = 0; e2 = TopExp_Explorer(s, TopAbs_SHELL)
        while e2.More(): nsh += 1; e2.Next()
        nf = 0; e3 = TopExp_Explorer(s, TopAbs_FACE)
        while e3.More(): nf += 1; e3.Next()
        m = TopTools_IndexedDataMapOfShapeListOfShape(); topexp.MapShapesAndAncestors(s, TopAbs_EDGE, TopAbs_FACE, m)
        fe = collections.Counter()
        for j in range(1, m.Size() + 1):
            fe[m.FindFromIndex(j).Size()] += 1
        key = ('valid' if ok else 'INVALID', 'v>0' if v > 0 else 'v<=0')
        stat[key] += 1
        if ALL or not ok or v <= 0:
            if shown < int(dict(a.split('=') for a in sys.argv if a.startswith('--max=')).get('--max', 40)):
                shown += 1
                print(lab, 'solid', k, 'valid', ok, 'vol %.1f' % v, 'shells', nsh, 'faces', nf, 'edge-face-count', dict(fe))
print(dict(stat))
