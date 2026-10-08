"""Diagnose why brep.solid() rejects a piece file: per stage (parse, bodies, faces made, sewing free edges, solid validity)."""
import sys, os, collections, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'v4', 'sds2-step-pipeline', 'decode'))
import brep
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid
from OCP.gp import gp_Pnt
from OCP.TopoDS import TopoDS
from OCP.TopAbs import TopAbs_SHELL
from OCP.TopExp import TopExp_Explorer
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.ShapeFix import ShapeFix_Solid
MM = 25.4

def edge_use(faces):
    E = collections.Counter()
    for f in faces:
        for l in brep.loops_of(f):
            for a, b in zip(l, l[1:] + l[:1]):
                E[(min(a, b), max(a, b))] += 1
    return E

def diag(path):
    data = open(path, 'rb').read()
    r = brep.parse(data)
    if r is None:
        print(path, 'parse None'); return
    V, F = r
    E = edge_use(F)
    print(path, 'nv', len(V), 'faces', len(F), 'edge use histogram', collections.Counter(E.values()))
    parts = brep.bodies(F)
    print('  bodies', len(parts), [len(p) for p in parts][:10])
    for nm, faces in (('raw', F), ('conform', brep.conform(V, F))):
        E = edge_use(faces)
        bad = {e: n for e, n in E.items() if n != 2}
        print(f'  [{nm}] non-manifold/free edges: {len(bad)}', list(bad.items())[:8])
        # planarity of each face
        npl = 0
        for f in faces:
            for l in brep.loops_of(f)[:1]:
                P = V[l]; c = P.mean(0)
                n = sum(np.cross(P[i] - c, P[(i + 1) % len(P)] - c) for i in range(len(P)))
                if np.linalg.norm(n) < 1e-12: continue
                n /= np.linalg.norm(n)
                if np.abs((P - c) @ n).max() > 1e-3: npl += 1
        print(f'  [{nm}] non-planar faces (>1e-3 in): {npl}')
        sew = BRepBuilderAPI_Sewing(1e-3 * MM); made = 0; failed = 0
        for f in faces:
            ls = brep.loops_of(f)
            if not ls: continue
            poly = BRepBuilderAPI_MakePolygon()
            for i in ls[0]: poly.Add(gp_Pnt(*(V[i] * MM)))
            poly.Close()
            mf = BRepBuilderAPI_MakeFace(poly.Wire(), True)
            if mf.IsDone(): sew.Add(mf.Face()); made += 1
            else: failed += 1
        sew.Perform()
        print(f'  [{nm}] faces made {made}, MakeFace failed {failed}, free edges after sewing {sew.NbFreeEdges()}, multiple edges {sew.NbMultipleEdges()}')
    s = brep.solid(V, F)
    print('  brep.solid ->', None if s is None else ('valid' if BRepCheck_Analyzer(s).IsValid() else 'invalid'))
    return V, F

if __name__ == '__main__':
    for p in sys.argv[1:]:
        diag(p)
