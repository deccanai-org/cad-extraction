#!/usr/bin/env python3
"""diag_open.py IFC GID - the product body and each opening body as OCC solids (world), bboxes, volumes, OCC cut result"""
import sys, os
import ifcopenshell, ifcopenshell.geom
import ifcopenshell.ifcopenshell_wrapper as WR
from OCC.Core.BRepTools import breptools
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRep import BRep_Builder
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut
f = ifcopenshell.open(sys.argv[1])
st = ifcopenshell.geom.settings(); st.set('use-world-coords', True); st.set('iterator-output', WR.SERIALIZED)
st0 = ifcopenshell.geom.settings(); st0.set('use-world-coords', True); st0.set('iterator-output', WR.SERIALIZED); st0.set('disable-opening-subtractions', True)
def shape(e, s):
    sh = ifcopenshell.geom.create_shape(s, e)
    d = sh.geometry.brep_data
    fn = '/tmp/_do_%d.brep' % os.getpid()
    (open(fn, 'wb') if isinstance(d, bytes) else open(fn, 'w')).write(d)
    x = TopoDS_Shape(); breptools.Read(x, fn, BRep_Builder()); return x
def vol(x):
    g = GProp_GProps(); brepgprop.VolumeProperties(x, g); return g.Mass() * 1e9
def bb(x):
    b = Bnd_Box(); brepbndlib.Add(x, b); return [round(v * 1000, 1) for v in b.Get()]
for gid in sys.argv[2:]:
    e = f.by_guid(gid)
    print('=====', e)
    body = shape(e, st0)
    print('body vol', round(vol(body), 1), 'bbox', bb(body))
    try:
        cut = shape(e, st); print('kernel with openings vol', round(vol(cut), 1), 'bbox', bb(cut))
    except Exception as ex:
        print('kernel with openings ERR', ex)
    acc = body
    for o in e.HasOpenings:
        op = o.RelatedOpeningElement
        print(' opening', op, 'placement rel to', op.ObjectPlacement.PlacementRelTo if op.ObjectPlacement else None)
        rep = op.Representation.Representations[0]
        for it in rep.Items:
            print('   item', it)
            if it.is_a('IfcMappedItem'):
                print('     origin', it.MappingSource.MappingOrigin, 'target', it.MappingTarget)
                for si in it.MappingSource.MappedRepresentation.Items:
                    print('     src', si)
                    for y in f.traverse(si)[:20]:
                        print('        ', str(y)[:200])
        try:
            os_ = shape(op, st0)
            print('   opening solid vol', round(vol(os_), 1), 'bbox', bb(os_))
            c = BRepAlgoAPI_Cut(acc, os_); c.Build()
            print('   OCC cut done', c.IsDone(), 'vol after', round(vol(c.Shape()), 1))
            acc = c.Shape()
        except Exception as ex:
            print('   opening shape ERR', ex)
