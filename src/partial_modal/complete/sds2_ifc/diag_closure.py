"""diag_closure.py IFC GID - build the closure variants of one open source body and report validity per face"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ref'))
import numpy as np
import ifcopenshell
import restore_ifc as R
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
from OCP.gp import gp_Pnt

ifc = ifcopenshell.open(sys.argv[1])
gid = sys.argv[2]
scale = R.unit_scale_mm(ifc)
prod = [p for p in ifc.by_type('IfcProduct') if p.GlobalId == gid][0]
M = R.placement_matrix(ifc, prod)
M[:3, 3] *= scale
brep, T = R.faceted_breps(prod)[0]
faces = R.brep_faces(brep, M @ T, scale)


def face_ok(fc):
    wires = []
    for lp in fc:
        mp = BRepBuilderAPI_MakePolygon()
        for p in lp:
            mp.Add(gp_Pnt(*p))
        mp.Close()
        wires.append(mp.Wire())
    mf = BRepBuilderAPI_MakeFace(wires[0], True)
    for w in wires[1:]:
        mf.Add(w)
    if not mf.IsDone():
        return 'not_done'
    return 'ok' if BRepCheck_Analyzer(mf.Face()).IsValid() else 'invalid'


import collections
print('source faces', len(faces), collections.Counter(face_ok(fc) for fc in faces))
bad = [i for i, fc in enumerate(faces) if face_ok(fc) != 'ok']
for i in bad[:10]:
    fc = faces[i]
    print(' bad face', i, [len(l) for l in fc], R.plane_fit([p for l in fc for p in l])[2], R.newell(fc[0]))
res = R.close_open_body(faces)
print('closure', res['ok'], res.get('how'))
for fc in res['faces'][len(faces) - 1:]:
    pass
new = [fc for fc in res['faces'] if fc not in faces]
print('new faces', len(new), [face_ok(fc) for fc in new], [[len(l) for l in fc] for fc in new])
so, chk = R.occ_solid(res['faces'])
print('occ_solid', chk)
# per-face check in the built solid
ex = TopExp_Explorer(so, TopAbs_FACE)
nb = 0
n = 0
while ex.More():
    n += 1
    if not BRepCheck_Analyzer(ex.Current()).IsValid():
        nb += 1
    ex.Next()
print('faces in solid', n, 'invalid faces', nb)
# steelbuild's own exact builder
import steelbuild as SB
rec = dict(solids=[dict(faces=[[[list(p) for p in lp] for lp in fc] for fc in res['faces']])])
rep = []
sols = SB.exact_part(rec, rep)
for s in sols:
    print('steelbuild exact_part: valid', s.is_valid, 'volume', s.volume, 'report', rep)
# fixed variant
from OCP.ShapeFix import ShapeFix_Shape
fx = ShapeFix_Shape(so)
fx.Perform()
s2 = fx.Shape()
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
g = GProp_GProps()
BRepGProp.VolumeProperties_s(s2, g)
print('ShapeFix_Shape: valid', BRepCheck_Analyzer(s2).IsValid(), 'volume', g.Mass())
# which faces are invalid in the sewn solid, and why
from OCP.BRep import BRep_Tool
from OCP.TopoDS import TopoDS
from OCP.BRepGProp import BRepGProp
def fstat(f):
    return []
ex = TopExp_Explorer(so, TopAbs_FACE)
k = 0
while ex.More():
    f = ex.Current()
    if not BRepCheck_Analyzer(f).IsValid():
        g = GProp_GProps(); BRepGProp.SurfaceProperties_s(f, g)
        from OCP.TopAbs import TopAbs_VERTEX, TopAbs_EDGE
        ne = 0; e2 = TopExp_Explorer(f, TopAbs_EDGE)
        tolmax = 0
        while e2.More():
            ne += 1; tolmax = max(tolmax, BRep_Tool.Tolerance_s((getattr(TopoDS,'Edge_s',None) or TopoDS.Edge)(e2.Current()))); e2.Next()
        if k < 12: print('  invalid face area', round(g.Mass(), 3), 'edges', ne, 'max edge tol', tolmax, fstat(f))
        k += 1
    ex.Next()
# sewing the source faces alone (open shell): invalid faces?
so0, chk0 = R.occ_solid(faces)
print('source-only sewn', chk0)
ex = TopExp_Explorer(so0, TopAbs_FACE); nb0 = 0
while ex.More():
    nb0 += 0 if BRepCheck_Analyzer(ex.Current()).IsValid() else 1; ex.Next()
print('source-only invalid faces', nb0)

res2 = R.close_open_body(faces, force_region=True)
print('force_region closure', res2['ok'], res2.get('how'), [l.get('region_faces') for l in res2['details']['loops']])
so2, chk2 = R.occ_solid(res2['faces'])
print('force_region occ_solid', chk2)
sols = SB.exact_part(dict(solids=[dict(faces=[[[list(p) for p in lp] for lp in fc] for fc in res2['faces']])]))
for s in sols: print('force_region steelbuild valid', s.is_valid, s.volume)
