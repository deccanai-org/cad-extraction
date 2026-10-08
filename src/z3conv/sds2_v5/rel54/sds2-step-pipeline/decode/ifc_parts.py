"""Ground truth for connection material: every non-beam/column IFC element's piecemark, type, psets summary,
world bbox and centroid. usage: python ifc_parts.py <file.ifc> <out.csv>"""
import sys, csv, multiprocessing, collections
import numpy as np
import ifcopenshell, ifcopenshell.geom, ifcopenshell.util.element as ue

f = ifcopenshell.open(sys.argv[1])
els = [e for e in f.by_type("IfcElement") if not e.is_a("IfcBeam") and not e.is_a("IfcColumn") and not e.is_a("IfcMember")
       and not e.is_a("IfcElementAssembly")]
print(collections.Counter(e.is_a() for e in els))
ex = [e for e in els if e.is_a("IfcDiscreteAccessory")][:4]
for e in ex:
    print(e.is_a(), e.Name, e.ObjectType, e.Description, {k: dict(list(v.items())[:10]) for k, v in ue.get_psets(e).items()})
s = ifcopenshell.geom.settings(); s.set("use-world-coords", True)
it = ifcopenshell.geom.iterator(s, f, multiprocessing.cpu_count(), include=els)
w = csv.writer(open(sys.argv[2], "w", newline=""))
w.writerow(["guid", "type", "name", "objtype", "desc", "mat_piecemark", "cx", "cy", "cz", "minx", "miny", "minz", "maxx", "maxy", "maxz"])
n = 0
if it.initialize():
    while True:
        sh = it.get(); e = f.by_guid(sh.guid)
        v = np.array(sh.geometry.verts).reshape(-1, 3)
        g = ue.get_psets(e).get("SDS2_General", {})
        w.writerow([sh.guid, e.is_a(), e.Name, e.ObjectType, e.Description, g.get("Material_Piecemark"), *np.round(v.mean(0), 4), *np.round(v.min(0), 4), *np.round(v.max(0), 4)])
        n += 1
        if not it.next(): break
print("wrote", n)

