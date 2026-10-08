import ifcopenshell, ifcopenshell.geom as G, sys
sys.path.insert(0, 'tools'); import extract
f = extract.open_ifc(sys.argv[1]); p = f.by_guid(sys.argv[2])
s = G.settings(); s.set('use-world-coords', True); s.set('iterator-output', ifcopenshell.ifcopenshell_wrapper.SERIALIZED)
it = G.iterator(s, f, 1, include=[p])
assert it.initialize()
sh = it.get()
bd = sh.geometry.brep_data
open(sys.argv[3], 'w').write(bd if isinstance(bd, str) else bd.decode())
