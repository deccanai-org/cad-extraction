import sys, json, ifcopenshell
f = ifcopenshell.open(sys.argv[1])
p = f.by_guid(sys.argv[2])
print(p.is_a(), p.Name, 'openings', len(p.HasOpenings or []))
for r in p.Representation.Representations:
    print(' rep', r.RepresentationIdentifier, r.RepresentationType, [i.is_a() for i in r.Items])
    def walk(it, d=0):
        if d > 8: return
        s = '  ' * d + it.is_a()
        if it.is_a('IfcBooleanResult'):
            print(s, it.Operator); walk(it.FirstOperand, d + 1); walk(it.SecondOperand, d + 1)
        elif it.is_a('IfcMappedItem'):
            print(s, 'scale', getattr(it.MappingTarget, 'Scale', None)); [walk(x, d + 1) for x in it.MappingSource.MappedRepresentation.Items]
        elif it.is_a('IfcExtrudedAreaSolid'):
            pr = it.SweptArea; print(s, 'depth', it.Depth, pr.is_a(), {k: v for k, v in pr.get_info().items() if k not in ('id', 'type', 'Position')})
        else:
            print(s)
    for it in r.Items:
        walk(it, 1)
for rel in p.IsDefinedBy or []:
    if rel.is_a('IfcRelDefinesByProperties') and rel.RelatingPropertyDefinition.is_a('IfcElementQuantity'):
        for q in rel.RelatingPropertyDefinition.Quantities:
            print(' Q', q.is_a(), q.Name, getattr(q, 'VolumeValue', None) or getattr(q, 'WeightValue', None) or getattr(q, 'LengthValue', None) or getattr(q, 'AreaValue', None))
