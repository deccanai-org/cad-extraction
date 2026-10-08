"""Dump a summary of an SDS2-exported IFC: entity counts and a few sample members with placement."""
import sys, collections, ifcopenshell, ifcopenshell.util.placement as up, ifcopenshell.util.element as ue

f = ifcopenshell.open(sys.argv[1])
prods = f.by_type("IfcElement")
print("elements:", len(prods))
print(collections.Counter(p.is_a() for p in prods).most_common(15))
for p in f.by_type("IfcBeam")[:3] + f.by_type("IfcColumn")[:2] + f.by_type("IfcPlate")[:1]:
    print("----", p.is_a(), p.GlobalId, "Name=", p.Name, "Tag=", p.Tag, "ObjectType=", p.ObjectType, "Desc=", p.Description)
    m = up.get_local_placement(p.ObjectPlacement)
    print("  placement origin", [round(x, 2) for x in m[:3, 3]], "xaxis", [round(x, 3) for x in m[:3, 0]], "zaxis", [round(x, 3) for x in m[:3, 2]])
    for rep in p.Representation.Representations if p.Representation else []:
        print("  rep", rep.RepresentationIdentifier, rep.RepresentationType, [i.is_a() for i in rep.Items][:3])
    psets = ue.get_psets(p)
    for k, v in list(psets.items())[:4]:
        print("  pset", k, {a: b for a, b in list(v.items())[:12]})
u = f.by_type("IfcSIUnit")
print("units:", [(x.UnitType, x.Prefix, x.Name) for x in u][:5])
