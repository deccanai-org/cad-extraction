#!/usr/bin/env python3
"""Check census prof_area() against the ifcopenshell kernel's exact BRep (OCC volume / depth) for every distinct
profile entity in the given IFC files (up to N per type). usage: validate_profiles.py census.py FILE.ifc [...]"""
import sys, os, math, tempfile, collections, importlib.util, types
import ifcopenshell, ifcopenshell.geom as G
from OCC.Core.BRepTools import breptools
from OCC.Core.BRep import BRep_Builder
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
src = open(sys.argv[1]).read()
src = src.split("ap = argparse.ArgumentParser()")[0] + "\n" + src[src.index("Q = 1.0 - math.pi"):src.index("# ------------------------------------------------------------------ placement maths")]
ns = {}
exec(src, ns)
ns['A_SI'] = 1.0   # radians (all sample files declare RADIAN)
prof_area = ns['prof_area']
s = G.settings(); s.set('iterator-output', ifcopenshell.ifcopenshell_wrapper.SERIALIZED)
res = collections.defaultdict(list)
for fn in sys.argv[2:]:
    f = ifcopenshell.open(fn)
    import ifcopenshell.util.unit as uu
    L = float(uu.calculate_unit_scale(f))
    per = collections.Counter()
    for sol in f.by_type('IfcExtrudedAreaSolid'):
        pr = sol.SweptArea; t = pr.is_a()
        if per[t] >= 25: continue
        per[t] += 1
        A = prof_area(pr)
        try:
            sh = G.create_shape(s, sol)
            p = os.path.join(tempfile.gettempdir(), 'vp_%d.brep' % os.getpid())
            open(p, 'w').write(sh.brep_data)
            shape = TopoDS_Shape(); breptools.Read(shape, p, BRep_Builder())
            g = GProp_GProps(); brepgprop.VolumeProperties(shape, g); V = g.Mass()
        except Exception as e:
            res[t].append(('kernel_err', str(e)[:60])); continue
        dr = sol.ExtrudedDirection.DirectionRatios; cz = abs(dr[2]) / math.sqrt(sum(x*x for x in dr))
        Ak = V / (sol.Depth * cz * L)   # kernel area in m * file-unit ... normalise below
        Ak = V / (sol.Depth * L * cz) / (L * L) * L  # V [m3] / (depth[m]) -> area m2 -> / L^2 -> file units^2
        Ak = V / (sol.Depth * L * cz) / (L * L)
        res[t].append((round(A / Ak, 5) if A else None, getattr(pr, 'ProfileName', None)))
for t, v in sorted(res.items()):
    rs = [x[0] for x in v if isinstance(x[0], float)]
    print('%-34s n=%3d  census/kernel min %.5f max %.5f  none=%d  e.g. %s' % (t, len(v), min(rs) if rs else float('nan'), max(rs) if rs else float('nan'), sum(1 for x in v if x[0] is None), v[:2]))
