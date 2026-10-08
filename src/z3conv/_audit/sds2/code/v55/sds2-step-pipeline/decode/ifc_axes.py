"""Ground truth from an SDS2 IFC: per beam/column/brace, piecemark + section + world-space axis end points.

Axis = extent of the element's world vertices along their principal direction.
usage: python ifc_axes.py <file.ifc> <out.csv>
"""
import sys, csv, multiprocessing
import numpy as np
import ifcopenshell, ifcopenshell.geom, ifcopenshell.util.element as ue

f = ifcopenshell.open(sys.argv[1])
els = f.by_type("IfcBeam") + f.by_type("IfcColumn") + f.by_type("IfcMember")
s = ifcopenshell.geom.settings()
s.set("use-world-coords", True)
it = ifcopenshell.geom.iterator(s, f, multiprocessing.cpu_count(), include=els)
out = open(sys.argv[2], "w", newline="")
w = csv.writer(out)
w.writerow(["guid", "type", "piecemark", "section", "sds2_id", "ax", "ay", "az", "bx", "by", "bz", "length", "minx", "miny", "minz", "maxx", "maxy", "maxz"])
n = 0
if it.initialize():
    while True:
        sh = it.get()
        e = f.by_guid(sh.guid)
        v = np.array(sh.geometry.verts).reshape(-1, 3)
        c = v.mean(0)
        u, sv, vt = np.linalg.svd(v - c, full_matrices=False)
        d = vt[0]
        t = (v - c) @ d
        a, b = c + d * t.min(), c + d * t.max()
        g = ue.get_psets(e).get("SDS2_General", {})
        w.writerow([sh.guid, e.is_a(), g.get("Member_Piecemark", e.Name), g.get("Cross_Section", e.Description), g.get("id"),
                    *np.round(a, 4), *np.round(b, 4), round(float(t.max() - t.min()), 4), *np.round(v.min(0), 4), *np.round(v.max(0), 4)])
        n += 1
        if not it.next():
            break
print("wrote", n)

