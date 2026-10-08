#!/usr/bin/env python3
"""print a product's body representation tree and its openings (types, key parameters, sizes)"""
import sys, ifcopenshell
f = ifcopenshell.open(sys.argv[1])
def show(e, d=0, maxd=7, seen=None):
    seen = seen if seen is not None else set()
    if d > maxd: return
    attrs = []
    for i in range(len(e)):
        v = e[i]
        if isinstance(v, ifcopenshell.entity_instance):
            attrs.append('#%d=%s' % (v.id(), v.is_a()))
        elif isinstance(v, (list, tuple)):
            if v and isinstance(v[0], ifcopenshell.entity_instance):
                attrs.append('[%d x %s]' % (len(v), v[0].is_a()))
            else:
                attrs.append(str(v)[:80])
        else:
            attrs.append(repr(v)[:60])
    print('  ' * d + '#%d %s(%s)' % (e.id(), e.is_a(), ', '.join(attrs))[:300])
    if e.id() in seen: return
    seen.add(e.id())
    for i in range(len(e)):
        v = e[i]
        if isinstance(v, ifcopenshell.entity_instance) and not v.is_a('IfcCartesianPoint') and not v.is_a('IfcDirection'):
            show(v, d + 1, maxd, seen)
        elif isinstance(v, (list, tuple)) and v and isinstance(v[0], ifcopenshell.entity_instance) and len(v) <= 12:
            for x in v:
                if not x.is_a('IfcCartesianPoint') and not x.is_a('IfcDirection'):
                    show(x, d + 1, maxd, seen)
for g in sys.argv[2:]:
    p = f.by_guid(g) if not g.isdigit() else f.by_id(int(g))
    print('=== PRODUCT'); show(p, 0, 1)
    print('--- body'); show(p.Representation, 0, 8)
    print('--- placement'); show(p.ObjectPlacement, 0, 4)
    for r in p.HasOpenings or []:
        o = r.RelatedOpeningElement
        print('--- OPENING'); show(o, 0, 1); show(o.Representation, 0, 8); show(o.ObjectPlacement, 0, 3)
