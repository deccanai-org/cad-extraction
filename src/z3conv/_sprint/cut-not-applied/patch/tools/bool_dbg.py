"""bool_dbg.py IFC GUID : the part's boolean operands; OCC result of each subtraction (valid? volume) via the ifcopenshell kernel"""
import sys, ifcopenshell, ifcopenshell.geom
from OCC.Core.BRepCheck import BRepCheck_Analyzer
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
f = ifcopenshell.open(sys.argv[1]); e = f.by_guid(sys.argv[2])
print(e.is_a(), e.Name)
rep = [r for r in e.Representation.Representations if r.RepresentationIdentifier == 'Body'][0]
def walk(x, d=0):
    if x.is_a('IfcBooleanResult'):
        walk(x.FirstOperand, d + 1); print('  ' * d, 'DIFFERENCE with', x.SecondOperand.is_a(), x.SecondOperand.SweptArea.is_a(), getattr(x.SecondOperand.SweptArea, 'ProfileName', None), 'depth', round(x.SecondOperand.Depth, 2),
                                       'pos', [round(c, 2) for c in x.SecondOperand.Position.Location.Coordinates], 'z', [round(c, 4) for c in (x.SecondOperand.Position.Axis.DirectionRatios if x.SecondOperand.Position.Axis else (0, 0, 1))])
    else:
        print('  ' * d, 'BASE', x.is_a(), getattr(x, 'SweptArea', None) and x.SweptArea.is_a(), round(getattr(x, 'Depth', 0), 2))
for it in rep.Items: walk(it)
S = ifcopenshell.geom.settings(); S.set('use-python-opencascade', True)
try:
    sh = ifcopenshell.geom.create_shape(S, e).geometry
    g = GProp_GProps(); brepgprop.VolumeProperties(sh, g)
    print('kernel shape valid', BRepCheck_Analyzer(sh).IsValid(), 'volume', round(g.Mass() * 1e9))
except Exception as ex:
    print('kernel error', ex)
