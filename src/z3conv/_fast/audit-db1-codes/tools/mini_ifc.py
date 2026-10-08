"""mini_ifc.py IN.ifc OUT.ifc GUID [GUID...] [--drop-cuts k1,k2|all|holes|parts]: keep only these elements; optionally drop boolean
operands of their CSG chain (indices in application order, or every bolt hole / every non-hole cut)"""
import sys, ifcopenshell
a = sys.argv[1:]
drop = None
if '--drop-cuts' in a:
    k = a.index('--drop-cuts'); drop = a[k + 1]; a = a[:k] + a[k + 2:]
src, dst, keep = a[0], a[1], set(a[2:])
f = ifcopenshell.open(src)
for e in list(f.by_type('IfcElement')):
    if e.GlobalId not in keep:
        f.remove(e)
if drop:
    for g in keep:
        e = f.by_guid(g)
        rep = e.Representation.Representations[0]
        x = rep.Items[0]; ops = []
        while x.is_a('IfcBooleanResult'):
            ops.append(x.SecondOperand); x = x.FirstOperand
        ops = ops[::-1]
        def is_hole(o): return (o.SweptArea.ProfileName or '').startswith('BOLT_HOLE')
        if drop == 'all': kill = set(range(len(ops)))
        elif drop == 'holes': kill = {i for i, o in enumerate(ops) if is_hole(o)}
        elif drop == 'parts': kill = {i for i, o in enumerate(ops) if not is_hole(o)}
        else: kill = {int(t) for t in drop.split(',')}
        solid = x
        for i, o in enumerate(ops):
            if i not in kill:
                solid = f.createIfcBooleanResult('DIFFERENCE', solid, o)
        rep.Items = [solid]
        rep.RepresentationType = 'CSG' if solid.is_a('IfcBooleanResult') else 'SweptSolid'
f.write(dst)
print('kept', len(f.by_type('IfcElement')))
