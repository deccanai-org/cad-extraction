"""Write a copy of an IFC where the given products (GUIDs) carry no representation, so the converter skips
exactly those elements (the geometry kernel segfaults on them); prints what was excluded."""
import sys, json, ifcopenshell
src, dst = sys.argv[1], sys.argv[2]; guids = sys.argv[3:]
f = ifcopenshell.open(src); out = []
for g in guids:
    e = f.by_guid(g)
    items = [(r.RepresentationIdentifier, r.RepresentationType, [i.is_a() for i in r.Items][:4]) for r in (e.Representation.Representations if e.Representation else [])]
    out.append({"guid": g, "type": e.is_a(), "name": getattr(e, "Name", None), "object_type": getattr(e, "ObjectType", None), "representation": items})
    e.Representation = None
f.write(dst)
print(json.dumps(out))
