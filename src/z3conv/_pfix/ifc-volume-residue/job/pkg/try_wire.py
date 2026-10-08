#!/usr/bin/env python3
"""try_wire.py IFC GID... - profile curve dump + kernel create_shape (converter poly settings) with wire-check variants"""
import sys, os, importlib.util
import numpy as np
import ifcopenshell, ifcopenshell.geom
spec = importlib.util.spec_from_file_location('v6', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ifc2step6_dev3.py'))
v6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)
os.environ.setdefault('DEFLECTION', '0.005'); os.environ.setdefault('ANG_DEFLECTION', '0.6')
f = ifcopenshell.open(sys.argv[1])
for gid in sys.argv[2:]:
    e = f.by_guid(gid)
    it = e.Representation.Representations[0].Items[0]
    print('==', gid, e.Name, it)
    for x in list(f.traverse(it.SweptArea))[:30]:
        print('    ', str(x)[:220])
    for var in ({}, {'no-wire-intersection-check': True}, {'no-wire-intersection-check': True, 'no-wire-intersection-tolerance': True}, {'precision': 1e-3}):
        s, _, m = v6.kernel_settings('poly')
        ok = True
        for k, v in var.items():
            try:
                s.set(k, v)
            except Exception as ex:
                print('   cannot set', k, ex); ok = False
        if not ok:
            continue
        try:
            sh = ifcopenshell.geom.create_shape(s, e)
            V, faces, iids = v6.kernel_geometry(sh.geometry, m)
            print('   ', var, 'OK verts', len(V), 'faces', len(faces))
        except Exception as ex:
            print('   ', var, 'ERR', str(ex)[:120])
