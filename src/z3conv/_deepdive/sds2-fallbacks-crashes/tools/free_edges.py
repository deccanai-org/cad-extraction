"""Which edges stay free when brep._solid sews a piece file (inner loops included, like the converter).
usage: free_edges.py <decode dir> <piece file> ..."""
import sys, collections, numpy as np
sys.path.insert(0, sys.argv[1])
import brep
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing
from OCP.gp import gp_Pnt
from OCP.TopoDS import TopoDS
from OCP.BRep import BRep_Tool
from OCP.TopExp import TopExp
from OCP.TopAbs import TopAbs_VERTEX
from OCP.ShapeFix import ShapeFix_Face
MM = 25.4
for path in sys.argv[2:]:
    V, F = brep.parse(open(path, 'rb').read())
    W = V
    sew = BRepBuilderAPI_Sewing(1e-3 * MM)
    info = []
    for k, f in enumerate(F):
        ls = brep.loops_of(f)
        ls.sort(key=lambda l: -brep._area(W[l]))
        def wire(idx):
            p = BRepBuilderAPI_MakePolygon()
            for i in idx: p.Add(gp_Pnt(*(W[i] * MM)))
            p.Close(); return p.Wire() if p.IsDone() else None
        w0 = wire(ls[0]); mf = BRepBuilderAPI_MakeFace(w0, True)
        if not mf.IsDone(): info.append((k, 'MakeFace failed', len(ls))); continue
        for l in ls[1:]:
            w = wire(l)
            if w is not None: mf.Add(w)
        face = mf.Face()
        if len(ls) > 1:
            fx = ShapeFix_Face(face); fx.FixOrientation(); fx.Perform(); face = fx.Face()
        sew.Add(face)
        # revisits inside one loop (keyhole)
        for l in ls:
            if len(set(l)) != len(l): info.append((k, 'loop revisits a vertex', l))
    sew.Perform()
    print(path, 'faces', len(F), 'free edges', sew.NbFreeEdges(), 'multiple', sew.NbMultipleEdges(), 'degenerated', sew.NbDegeneratedShapes())
    for i in range(1, sew.NbFreeEdges() + 1):
        e = sew.FreeEdge(i)
        v1, v2 = TopExp.FirstVertex_s(e), TopExp.LastVertex_s(e)
        p1 = np.array(BRep_Tool.Pnt_s(v1).Coord()) / MM; p2 = np.array(BRep_Tool.Pnt_s(v2).Coord()) / MM
        # nearest vertex indices
        i1 = int(np.argmin(np.linalg.norm(V - p1, axis=1))); i2 = int(np.argmin(np.linalg.norm(V - p2, axis=1)))
        fs = [k for k, f in enumerate(F) if i1 in f and i2 in f]
        print('  free edge', np.round(p1, 4), np.round(p2, 4), 'len', round(float(np.linalg.norm(p2 - p1)), 5), 'v', i1, i2, 'faces', fs)
    for x in info[:10]: print('  ', x)
    # loops per face, faces with several loops
    ml = [(k, [len(l) for l in brep.loops_of(f)]) for k, f in enumerate(F) if len(brep.loops_of(f)) > 1]
    print('  multi-loop faces', ml[:10])
