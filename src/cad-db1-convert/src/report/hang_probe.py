"""mesh every product of an IFC separately (subprocess + timeout) with the fleet's ifcopenshell;
print which products hang or fail"""
import sys, subprocess, json, ifcopenshell
path = sys.argv[1]; f = ifcopenshell.open(path)
ids = [e.GlobalId for e in f.by_type("IfcProduct") if e.Representation]
print("ifcopenshell", ifcopenshell.version, "products", len(ids), flush=True)
code = r'''
import sys, ifcopenshell, ifcopenshell.geom
f = ifcopenshell.open(sys.argv[1]); e = f.by_guid(sys.argv[2])
s = ifcopenshell.geom.settings(); s.set(s.USE_WORLD_COORDS, True)
sh = ifcopenshell.geom.create_shape(s, e); print(len(sh.geometry.faces) // 3)
'''
bad = []
for g in ids:
    try:
        r = subprocess.run([sys.executable, "-c", code, path, g], capture_output=True, text=True, timeout=float(sys.argv[2]) if len(sys.argv) > 2 else 20)
        if r.returncode != 0: bad.append((g, "error", r.stderr.strip()[-200:]))
    except subprocess.TimeoutExpired:
        e = f.by_guid(g); bad.append((g, "HANG", e.is_a() + " " + (e.Name or "")))
        print("HANG", g, e.is_a(), e.Name, flush=True)
print("done; bad:", len(bad)); [print(b) for b in bad[:30]]
