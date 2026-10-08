#!/usr/bin/env python3
"""try_nullseg.py IFC GID... - drop IfcCompositeCurveSegments whose ParentCurve is $ (in memory) and retry the kernel"""
import sys, os, importlib.util
import numpy as np
import ifcopenshell, ifcopenshell.geom
spec = importlib.util.spec_from_file_location('v6', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ifc2step6_dev3.py'))
v6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)
os.environ.setdefault('DEFLECTION', '0.005'); os.environ.setdefault('ANG_DEFLECTION', '0.6')
f = ifcopenshell.open(sys.argv[1])
n = tot = 0
for cc in f.by_type('IfcCompositeCurve'):
    tot += 1
    segs = cc.Segments or ()
    keep = [s for s in segs if getattr(s, 'ParentCurve', None) is not None]
    if keep and len(keep) < len(segs):
        cc.Segments = keep; n += 1
print('composite curves', tot, 'with null segments repaired', n)
for gid in sys.argv[2:]:
    e = f.by_guid(gid)
    s, _, m = v6.kernel_settings('tri')
    try:
        sh = ifcopenshell.geom.create_shape(s, e)
        V, faces, iids = v6.kernel_geometry(sh.geometry, m)
        t = 0.0
        for fc in faces:
            lp = fc[0]
            for i in range(1, len(lp) - 1):
                t += np.dot(V[lp[0]], np.cross(V[lp[i]], V[lp[i + 1]])) / 6.0
        print(gid, 'OK faces', len(faces), 'volume mm3', round(t, 1), 'expected 660.4*304.8*19.05 =', round(660.400055*304.799988*19.05, 1))
    except Exception as ex:
        print(gid, 'ERR', str(ex)[:150])
