#!/usr/bin/env python3
"""does the kernel close an OPEN composite curve once the ParentCurve-less segment is dropped (patch 2)? synthetic plates"""
import importlib.util, json
import ifcopenshell, ifcopenshell.geom
spec = importlib.util.spec_from_file_location('v6', '/work/agentwork/ifc-volume-residue-review/pkg/conv_comb/ifc2step6.py')
v6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.BRepTools import breptools
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRep import BRep_Builder
import ifcopenshell.ifcopenshell_wrapper as WR


def build(case):
    f = ifcopenshell.file(schema='IFC2X3')
    P = lambda *c: f.createIfcCartesianPoint([float(x) for x in c])
    D = lambda *c: f.createIfcDirection([float(x) for x in c])
    org = f.createIfcAxis2Placement3D(P(0, 0, 0), D(0, 0, 1), D(1, 0, 0))
    ctx = f.createIfcGeometricRepresentationContext(None, 'Model', 3, 1e-5, org, None)
    un = f.createIfcUnitAssignment([f.createIfcSIUnit(None, 'LENGTHUNIT', 'MILLI', 'METRE')])
    proj = f.createIfcProject(ifcopenshell.guid.new(), None, 'p', None, None, None, None, [ctx], un)
    if case == 'closed':
        pts = [(0, 0), (457.2, 0), (457.2, 304.8), (-203.2, 304.8), (-203.2, 0), (0, 0)]
    else:   # open: last side missing (gap from (-203.2,0) back to (0,0) is NOT closed; first point moved)
        pts = [(0, 0), (457.2, 0), (457.2, 304.8), (-203.2, 304.8), (-203.2, 100)]
    pl = f.createIfcPolyline([P(*p) for p in pts])
    segs = []
    if case != 'nonull_open':
        segs.append(f.createIfcCompositeCurveSegment('CONTINUOUS', True, None))
    segs.append(f.createIfcCompositeCurveSegment('CONTINUOUS', True, pl))
    cc = f.createIfcCompositeCurve(segs, False)
    prof = f.createIfcArbitraryClosedProfileDef('AREA', None, cc)
    sol = f.createIfcExtrudedAreaSolid(prof, f.createIfcAxis2Placement3D(P(0, 0, 0), None, None), D(0, 0, 1), 19.05)
    rep = f.createIfcShapeRepresentation(ctx, 'Body', 'SweptSolid', [sol])
    pds = f.createIfcProductDefinitionShape(None, None, [rep])
    lp = f.createIfcLocalPlacement(None, f.createIfcAxis2Placement3D(P(0, 0, 0), None, None))
    pr = f.createIfcPlate(ifcopenshell.guid.new(), None, 'SHEAR TAB', None, None, lp, pds, None)
    return f, pr


def vol(f, pr):
    s = ifcopenshell.geom.settings(); s.set('use-world-coords', True); s.set('iterator-output', WR.SERIALIZED)
    try:
        sh = ifcopenshell.geom.create_shape(s, pr)
    except Exception as e:
        return 'FAIL: ' + str(e)[:80]
    d = sh.geometry.brep_data
    fn = '/tmp/_synth.brep'
    (open(fn, 'wb') if isinstance(d, bytes) else open(fn, 'w')).write(d)
    x = TopoDS_Shape(); breptools.Read(x, fn, BRep_Builder())
    g = GProp_GProps(); brepgprop.VolumeProperties(x, g)
    return round(g.Mass() * 1e9, 1)


for case in ('closed', 'open', 'nonull_open'):
    f, pr = build(case)
    before = vol(f, pr)
    n = v6.repair_null_curve_segments(f)
    after = vol(f, pr)
    print(json.dumps({'case': case, 'kernel_before_patch': before, 'curves_changed': n, 'kernel_after_patch': after,
                      'closed_area_x_depth': round((660.4 * 304.8) * 19.05, 1)}))
