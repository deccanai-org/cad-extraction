#!/usr/bin/env python3
"""try_settings.py IFC GID... - kernel polyhedral output of a product under setting variants: faces, mesh volume"""
import sys, os, importlib.util
import numpy as np
import ifcopenshell, ifcopenshell.geom
spec = importlib.util.spec_from_file_location('v6', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ifc2step6_dev3.py'))
v6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)
f = ifcopenshell.open(sys.argv[1])
s0 = ifcopenshell.geom.settings()
print('available settings:', [k for k in s0.setting_names()] if hasattr(s0, 'setting_names') else '?')
def meshvol(V, faces):
    t = 0.0
    for fc in faces:
        lp = fc[0]
        for i in range(1, len(lp) - 1):
            a, b, c = V[lp[0]], V[lp[i]], V[lp[i + 1]]
            t += np.dot(a, np.cross(b, c)) / 6.0
    return t
VARS = [{}, {'reorient-shells': True}, {'boolean-attempt-2d': False}, {'reorient-shells': True, 'boolean-attempt-2d': False}, {'disable-opening-subtractions': True}]
for gid in sys.argv[2:]:
    e = f.by_guid(gid)
    print('==', gid, e.is_a(), e.Name)
    for var in VARS:
        for mode in ('poly', 'tri'):
            s, _, m = v6.kernel_settings(mode)
            ok = True
            for k, v in var.items():
                try:
                    s.set(k, v)
                except Exception as ex:
                    ok = False; print('   cannot set', k, ex)
            try:
                sh = ifcopenshell.geom.create_shape(s, e)
                V, faces, iids = v6.kernel_geometry(sh.geometry, m)
                mv = meshvol(V, faces) if mode == 'tri' else None
                print('  ', var, mode, 'verts', len(V), 'faces', len(faces), 'meshvol(tri)', None if mv is None else round(mv, 1))
            except Exception as ex:
                print('  ', var, mode, 'ERR', type(ex).__name__, str(ex)[:150])
