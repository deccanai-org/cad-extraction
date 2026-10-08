import sys, hashlib, json
import numpy as np
import ifcopenshell, ifcopenshell.geom
import ifcopenshell.ifcopenshell_wrapper as W
ifc, out, threads = sys.argv[1], sys.argv[2], int(sys.argv[3])
f = ifcopenshell.open(ifc)
s = ifcopenshell.geom.settings()
for key, val in (("use-world-coords", True), ("weld-vertices", True)):
    s.set(key, val)
s.set("triangulation-type", W.POLYHEDRON_WITH_HOLES)
it = ifcopenshell.geom.iterator(s, f, threads)
res = {}
if it.initialize():
    while True:
        sh = it.get()
        g = sh.geometry
        V = np.array(g.verts, np.float64)
        pf = g.polyhedral_faces_with_holes
        fs = [[list(lp) for lp in fc] for fc in pf] if pf else None
        res[sh.id] = [hashlib.sha256(V.tobytes()).hexdigest()[:12], hashlib.sha256(json.dumps(fs).encode()).hexdigest()[:12], len(V)]
        if not it.next():
            break
json.dump(res, open(out, 'w'), sort_keys=True)
print(len(res))
