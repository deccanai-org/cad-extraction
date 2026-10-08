"""mesh every product of an IFC separately (subprocess + timeout, 24 in parallel) with this env's
ifcopenshell; print products that hang or fail, with their profile/shape type"""
import sys, subprocess, ifcopenshell
from concurrent.futures import ThreadPoolExecutor
path = sys.argv[1]; T = float(sys.argv[2]) if len(sys.argv) > 2 else 30; f = ifcopenshell.open(path)
ids = [e.GlobalId for e in f.by_type("IfcProduct") if e.Representation]
print("ifcopenshell", ifcopenshell.version, "products", len(ids), flush=True)
code = r'''
import sys, ifcopenshell, ifcopenshell.geom
f = ifcopenshell.open(sys.argv[1]); e = f.by_guid(sys.argv[2])
s = ifcopenshell.geom.settings(); s.set(s.USE_WORLD_COORDS, True)
sh = ifcopenshell.geom.create_shape(s, e); print(len(sh.geometry.faces) // 3)
'''
def desc(e):
    it = e.Representation.Representations[0].Items[0]
    kinds = [it.is_a()]
    while it.is_a("IfcBooleanResult"): it = it.FirstOperand; kinds.append(it.is_a())
    prof = getattr(getattr(it, "SweptArea", None), "is_a", lambda: "")()
    npts = len(it.SweptArea.OuterCurve.Points) if prof == "IfcArbitraryClosedProfileDef" and it.SweptArea.OuterCurve.is_a("IfcPolyline") else None
    return f"{e.is_a()} {e.Name} {'/'.join(kinds)} {prof} pts={npts} depth={round(getattr(it,'Depth',0),2)}"
def one(g):
    try:
        r = subprocess.run([sys.executable, "-c", code, path, g], capture_output=True, text=True, timeout=T)
        return (g, "error", r.stderr.strip()[-160:]) if r.returncode else None
    except subprocess.TimeoutExpired:
        return (g, "HANG", desc(f.by_guid(g)))
with ThreadPoolExecutor(24) as ex: bad = [b for b in ex.map(one, ids) if b]
print("done; bad:", len(bad)); [print(b) for b in bad[:40]]
