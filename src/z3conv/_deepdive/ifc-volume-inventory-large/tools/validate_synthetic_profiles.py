#!/usr/bin/env python3
"""census v3 prof_area() vs the ifcopenshell kernel's exact B-rep on synthetic profiles (types without data-3 samples).
usage: validate_synthetic_profiles.py census.py"""
import sys, os, math, tempfile
import ifcopenshell, ifcopenshell.geom as G, ifcopenshell.guid
from OCC.Core.BRepTools import breptools
from OCC.Core.BRep import BRep_Builder
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
src = open(sys.argv[1]).read()
src = src.split("ap = argparse.ArgumentParser()")[0] + "\n" + src[src.index("Q = 1.0 - math.pi"):src.index("# ------------------------------------------------------------------ placement maths")]
ns = {}; exec(src, ns); ns['A_SI'] = 1.0
s = G.settings(); s.set('iterator-output', ifcopenshell.ifcopenshell_wrapper.SERIALIZED)
def kernel_area(f, pr):
    sol = f.createIfcExtrudedAreaSolid(pr, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0., 0., 0.)), None, None), f.createIfcDirection((0., 0., 1.)), 1.0)
    sh = G.create_shape(s, sol); p = os.path.join(tempfile.gettempdir(), 'vsp_%d.brep' % os.getpid()); open(p, 'w').write(sh.brep_data)
    x = TopoDS_Shape(); breptools.Read(x, p, BRep_Builder()); g = GProp_GProps(); brepgprop.VolumeProperties(x, g); os.remove(p)
    return g.Mass()
cases = []
ONLY = int(sys.argv[2]) if len(sys.argv) > 2 else None
if ONLY is None:
    import subprocess
    for n in range(40):
        r = subprocess.run([sys.executable, __file__, sys.argv[1], str(n)], capture_output=True, text=True)
        out = [l for l in r.stdout.splitlines() if l.strip()]
        if r.returncode == 0 and not out:
            break
        line = out[-1] if out else 'case %d' % n
        print(line.replace('...', 'kernel crashed (rc %d): census returns %s' % (r.returncode, 'None' if 'no lips' in line else '?')) if r.returncode not in (0,) else line)
    sys.exit(0)
idx = -1
for schema in ('IFC2X3', 'IFC4'):
    f = ifcopenshell.file(schema=schema)
    # a project with explicit units (metre, radian): the kernel reads FlangeSlope etc. through the file's angle unit
    ua = f.createIfcUnitAssignment([f.createIfcSIUnit(None, 'LENGTHUNIT', None, 'METRE'), f.createIfcSIUnit(None, 'PLANEANGLEUNIT', None, 'RADIAN')])
    f.create_entity('IfcProject', GlobalId=ifcopenshell.guid.new(), Name='synthetic', UnitsInContext=ua)
    P = lambda: f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0., 0.)), None)
    C = []
    E = lambda t, **kw: f.create_entity(t, ProfileType='AREA', Position=P(), **kw)
    C.append(('C lips + fillet', E('IfcCShapeProfileDef', Depth=0.2, Width=0.08, WallThickness=0.003, Girth=0.02, InternalFilletRadius=0.004)))
    C.append(('C no lips + fillet', E('IfcCShapeProfileDef', Depth=0.2, Width=0.08, WallThickness=0.003, Girth=0.0, InternalFilletRadius=0.004)))
    C.append(('Z + radii', E('IfcZShapeProfileDef', Depth=0.3, FlangeWidth=0.1, WebThickness=0.008, FlangeThickness=0.012, FilletRadius=0.01, EdgeRadius=0.004)))
    C.append(('RoundedRectangle', E('IfcRoundedRectangleProfileDef', XDim=0.4, YDim=0.2, RoundingRadius=0.03)))
    C.append(('Ellipse', E('IfcEllipseProfileDef', SemiAxis1=0.3, SemiAxis2=0.1)))
    C.append(('L + fillet + edge', E('IfcLShapeProfileDef', Depth=0.15, Width=0.1, Thickness=0.012, FilletRadius=0.012, EdgeRadius=0.006, LegSlope=0.0)))
    C.append(('U slope 0.1651 + fillet + edge', E('IfcUShapeProfileDef', Depth=0.3, FlangeWidth=0.09, WebThickness=0.008, FlangeThickness=0.012, FilletRadius=0.012, EdgeRadius=0.005, FlangeSlope=0.1651)))
    C.append(('U slope + fillet, EdgeRadius unset', E('IfcUShapeProfileDef', Depth=0.3, FlangeWidth=0.09, WebThickness=0.008, FlangeThickness=0.012, FilletRadius=0.012, FlangeSlope=0.1651)))
    C.append(('T + fillet + edges', E('IfcTShapeProfileDef', Depth=0.2, FlangeWidth=0.25, WebThickness=0.01, FlangeThickness=0.016, FilletRadius=0.015, FlangeEdgeRadius=0.004, WebEdgeRadius=0.003, WebSlope=0.0, FlangeSlope=0.0)))
    if schema == 'IFC2X3':
        C.append(('AsymmetricI 2x3', E('IfcAsymmetricIShapeProfileDef', OverallWidth=0.3, OverallDepth=0.9, WebThickness=0.012, FlangeThickness=0.025, FilletRadius=0.02, TopFlangeWidth=0.2, TopFlangeThickness=0.018, TopFlangeFilletRadius=0.015)))
    else:
        C.append(('AsymmetricI 4 (plate girder)', E('IfcAsymmetricIShapeProfileDef', BottomFlangeWidth=0.3, OverallDepth=0.9, WebThickness=0.012, BottomFlangeThickness=0.025, BottomFlangeFilletRadius=0.02, TopFlangeWidth=0.2, TopFlangeThickness=0.018, TopFlangeFilletRadius=0.015, BottomFlangeEdgeRadius=0.0, BottomFlangeSlope=0.0, TopFlangeEdgeRadius=0.0, TopFlangeSlope=0.0)))
        C.append(('I + FlangeEdgeRadius (IFC4)', E('IfcIShapeProfileDef', OverallWidth=0.2, OverallDepth=0.4, WebThickness=0.009, FlangeThickness=0.014, FilletRadius=0.02, FlangeEdgeRadius=0.005, FlangeSlope=0.0)))
    base = f.createIfcRectangleProfileDef('AREA', None, P(), 0.3, 0.1)
    op = f.createIfcCartesianTransformationOperator2D(f.createIfcDirection((-1., 0.)), f.createIfcDirection((0., 1.)), f.createIfcCartesianPoint((0., 0.)), 1.0)
    C.append(('Derived (mirrored rectangle)', f.createIfcDerivedProfileDef('AREA', None, base, op, None)))
    poly = f.createIfcPolyline([f.createIfcCartesianPoint(p) for p in ((0., 0.), (0.4, 0.), (0.4, 0.3), (0., 0.3), (0., 0.))])
    hole = f.createIfcPolyline([f.createIfcCartesianPoint(p) for p in ((0.1, 0.1), (0.2, 0.1), (0.2, 0.2), (0.1, 0.2), (0.1, 0.1))])
    C.append(('ArbitraryWithVoids', f.createIfcArbitraryProfileDefWithVoids('AREA', None, poly, [hole])))
    if schema == 'IFC4':
        pl = f.createIfcCartesianPointList2D(((0., 0.), (0.5, 0.), (0.5, 0.2), (0., 0.2)))
        C.append(('IndexedPolyCurve (no arcs)', f.createIfcArbitraryClosedProfileDef('AREA', None, f.createIfcIndexedPolyCurve(pl, None, False))))
    for nm, pr in C:
        idx += 1
        if idx != ONLY:
            continue
        print('%-6s %-34s ...' % (schema, nm), flush=True)
        try:
            k = kernel_area(f, pr)
        except Exception as e:
            cases.append((schema, nm, None, None, 'kernel error %s' % str(e)[:50])); continue
        a = ns['prof_area'](pr)
        cases.append((schema, nm, a, k, ('ratio %.5f' % (a / k)) if a else 'census: no expectation'))
for c in cases:
    print('%-6s %-34s census %-12s kernel %-12s %s' % (c[0], c[1], ('%.6g' % c[2]) if c[2] else c[2], ('%.6g' % c[3]) if c[3] else c[3], c[4]))
