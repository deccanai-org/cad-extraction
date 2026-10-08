"""ifc_one.py IFC GUID32... : dump representation items and quantities of Tekla IFC elements (by expanded GUID without dashes)"""
import sys, ifcopenshell, ifcopenshell.guid
f = ifcopenshell.open(sys.argv[1]); want = set(sys.argv[2:])
for e in f.by_type('IfcElement'):
    g = ifcopenshell.guid.expand(e.GlobalId).upper().replace('-', '')
    if g not in want: continue
    print('==', e.is_a(), e.Name, e.ObjectType, g)
    for r in e.Representation.Representations:
        print('   rep', r.RepresentationIdentifier, r.RepresentationType, [i.is_a() for i in r.Items])
        for it in r.Items:
            def walk(x, d=0):
                s = '      ' + '  ' * d + x.is_a()
                if x.is_a('IfcExtrudedAreaSolid'): s += ' depth %.1f profile %s' % (x.Depth, x.SweptArea.is_a() + ' ' + str(x.SweptArea.ProfileName))
                if x.is_a('IfcBooleanResult'): print(s + ' ' + x.Operator); walk(x.FirstOperand, d + 1); walk(x.SecondOperand, d + 1); return
                if x.is_a('IfcHalfSpaceSolid') or x.is_a('IfcPolygonalBoundedHalfSpace'): s += ' plane ' + str(x.BaseSurface.Position.Location.Coordinates) + ' n ' + str(x.BaseSurface.Position.Axis.DirectionRatios if x.BaseSurface.Position.Axis else None)
                print(s)
            walk(it)
    for r in e.IsDefinedBy or []:
        if r.is_a('IfcRelDefinesByProperties'):
            pd = r.RelatingPropertyDefinition
            if pd.is_a('IfcPropertySet') and pd.Name == 'BaseQuantities':
                print('   ', [(p.Name, round(float(p.NominalValue.wrappedValue), 6)) for p in pd.HasProperties if p.Name in ('Length', 'NetVolume', 'GrossVolume', 'NetWeight', 'GrossWeight')])
    for r in e.HasOpenings or []:
        print('   opening', r.RelatedOpeningElement)
