#!/usr/bin/env python3
"""Count products whose Body is purely faceted (the converter's transcode path writes them WITHOUT applying
IfcRelVoidsElement openings) and that have openings. usage: faceted_openings.py FILE.ifc [...]"""
import sys, collections, ifcopenshell
FAC = ("IfcFacetedBrep", "IfcFacetedBrepWithVoids", "IfcShellBasedSurfaceModel", "IfcFaceBasedSurfaceModel",
       "IfcPolygonalFaceSet", "IfcTriangulatedFaceSet")
def leaf(items):
    out = []
    for it in items:
        if it.is_a('IfcMappedItem'):
            out += leaf(it.MappingSource.MappedRepresentation.Items)
        else:
            out.append(it)
    return out
for fn in sys.argv[1:]:
    try:
        f = ifcopenshell.open(fn)
    except Exception as e:
        print(fn, 'open error', e); continue
    c = collections.Counter(); ex = []
    for p in f.by_type('IfcProduct'):
        if p.is_a() in ('IfcOpeningElement', 'IfcOpeningStandardCase', 'IfcSpace', 'IfcGrid', 'IfcAnnotation', 'IfcVirtualElement'):
            continue
        rep = p.Representation
        if rep is None:
            continue
        items = [it for r in rep.Representations if r.RepresentationIdentifier in (None, 'Body', 'Facetation') for it in r.Items]
        if not items:
            continue
        lf = leaf(items)
        fac = all(x.is_a() in FAC for x in lf)
        ops = len(getattr(p, 'HasOpenings', None) or [])
        c['faceted' if fac else 'other'] += 1
        if ops:
            c['with_openings_faceted' if fac else 'with_openings_other'] += 1
            if fac and len(ex) < 3:
                ex.append((p.is_a(), p.GlobalId, p.Name, ops))
    print(fn.split('/')[-1][:30], f.schema, dict(c), ex)
