#!/usr/bin/env python3
"""bool_steps.py IFC GID... - walk the DIFFERENCE chain of a product body: B-rep volume of every intermediate result
(create_shape on the representation item) and of each cutting operand -> which cut removed nothing / too much.
Also the whole product under precision-factor variants."""
import sys, os
import ifcopenshell, ifcopenshell.geom
import ifcopenshell.ifcopenshell_wrapper as WR
from OCC.Core.BRepTools import breptools
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRep import BRep_Builder
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
f = ifcopenshell.open(sys.argv[1])
def vol_of(x, extra=None):
    s = ifcopenshell.geom.settings(); s.set('iterator-output', WR.SERIALIZED)
    if x.is_a('IfcProduct'):
        s.set('use-world-coords', True)
    for k, v in (extra or {}).items():
        s.set(k, v)
    try:
        sh = ifcopenshell.geom.create_shape(s, x)
        d = (sh.geometry.brep_data if hasattr(sh, 'geometry') else sh.brep_data)
        fn = '/tmp/_bs_%d.brep' % os.getpid()
        (open(fn, 'wb') if isinstance(d, bytes) else open(fn, 'w')).write(d)
        t = TopoDS_Shape(); breptools.Read(t, fn, BRep_Builder())
        g = GProp_GProps(); brepgprop.VolumeProperties(t, g); return g.Mass()
    except Exception as ex:
        return 'ERR %s' % str(ex)[:80]
for gid in sys.argv[2:]:
    e = f.by_guid(gid)
    it = e.Representation.Representations[0].Items[0]
    if it.is_a('IfcMappedItem'):
        it = it.MappingSource.MappedRepresentation.Items[0]
    chain = []
    x = it
    while x.is_a('IfcBooleanResult'):
        chain.append(x); x = x.FirstOperand
    print('==', gid, e.Name, 'depth', len(chain), 'base', x.is_a(), 'base vol', vol_of(x))
    if os.environ.get('ONLY_PF'):
        chain = []
    # innermost first
    for b in reversed(chain):
        print('   after cut by', b.SecondOperand.is_a(), str(b.SecondOperand)[:90], '-> result vol', vol_of(b), ' operand vol', vol_of(b.SecondOperand) if not b.SecondOperand.is_a('IfcHalfSpaceSolid') else 'halfspace')
    for pf in (None, 0.1, 10.0, 100.0, 1000.0):
        print('   product with precision-factor', pf, vol_of(e, {'precision-factor': pf} if pf else None))
