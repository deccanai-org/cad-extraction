#!/usr/bin/env python3
"""Diagnose why parts fall outside the per-part volume tolerance: print body items, profile, fillets, openings.
usage: explain_parts.py FILE.ifc GID [GID ...]   (or --names NAME ...)"""
import sys, ifcopenshell
f = ifcopenshell.open(sys.argv[1])
keys = sys.argv[2:]
byname = '--names' in keys
keys = [k for k in keys if k != '--names']
for p in f.by_type('IfcProduct'):
    if (p.Name if byname else p.GlobalId) not in keys:
        continue
    print('====', p.is_a(), p.GlobalId, p.Name, getattr(p, 'ObjectType', None))
    ops = [r.RelatedOpeningElement for r in (getattr(p, 'HasOpenings', None) or [])]
    print('  openings:', len(ops), [o.is_a() for o in ops][:5])
    for o in ops[:3]:
        for r in (o.Representation.Representations if o.Representation else []):
            print('    opening rep', r.RepresentationIdentifier, r.RepresentationType, [it.is_a() for it in r.Items])
    if p.Representation:
        for r in p.Representation.Representations:
            print('  rep', r.RepresentationIdentifier, r.RepresentationType, [it.is_a() for it in r.Items])
            for it in r.Items:
                src = it
                if it.is_a('IfcMappedItem'):
                    src = it.MappingSource.MappedRepresentation
                    print('    mapped ->', src.RepresentationType, [x.is_a() for x in src.Items], 'scale', it.MappingTarget.Scale)
                    for x in src.Items:
                        if x.is_a('IfcExtrudedAreaSolid'):
                            print('      ', x.SweptArea)
                            print('       depth', x.Depth, 'dir', x.ExtrudedDirection.DirectionRatios)
                elif it.is_a('IfcExtrudedAreaSolid'):
                    print('      ', it.SweptArea)
                    print('       depth', it.Depth, 'dir', it.ExtrudedDirection.DirectionRatios)
                elif it.is_a('IfcBooleanResult'):
                    print('      bool', it.Operator, it.FirstOperand.is_a(), it.SecondOperand.is_a())
