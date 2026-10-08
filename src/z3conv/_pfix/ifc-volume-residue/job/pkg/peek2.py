import sys
import ifcopenshell
f = ifcopenshell.open(sys.argv[1])
for i in sys.argv[2:]:
    e = f.by_id(int(i))
    it = e.Representation.Representations[0].Items[0]
    mr = it.MappingSource.MappedRepresentation
    print('==', i, e.Name, 'map origin', it.MappingSource.MappingOrigin, 'target', it.MappingTarget)
    print('  mapped rep', mr, 'items', len(mr.Items))
    for x in mr.Items[:3]:
        print('   ', str(x)[:300])
        for y in list(f.traverse(x))[1:12]:
            print('       ', str(y)[:200])
    for rel in e.HasOpenings:
        op = rel.RelatedOpeningElement
        print('  opening', op.GlobalId, op.Name, 'placement', op.ObjectPlacement)
        for r in op.Representation.Representations:
            for x in r.Items:
                print('    op item', str(x)[:200])
                src = x.MappingSource.MappedRepresentation.Items if x.is_a('IfcMappedItem') else [x]
                for s in src[:2]:
                    print('      ', str(s)[:200], 'traverse', len(list(f.traverse(s))))
