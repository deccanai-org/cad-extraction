#!/usr/bin/env python3
"""try_vol.py IFC GID... - one product's volume under kernel variants: B-rep (serialized, OCC GProp), triangle mesh
(signed), polyhedral faces (signed, loops fan-triangulated, holes as given), with boolean-attempt-2d on/off and the
converter's deflection settings"""
import sys, os, importlib.util
import numpy as np
import ifcopenshell, ifcopenshell.geom
import ifcopenshell.ifcopenshell_wrapper as WR
from OCC.Core.BRepTools import breptools
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRep import BRep_Builder
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.BRepCheck import BRepCheck_Analyzer
spec = importlib.util.spec_from_file_location('v6', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ifc2step6_dev3.py'))
v6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)
os.environ.setdefault('DEFLECTION', '0.005'); os.environ.setdefault('ANG_DEFLECTION', '0.6')
f = ifcopenshell.open(sys.argv[1])
def sv(V, loops):
    t = 0.0
    for lp in loops:
        for i in range(1, len(lp) - 1):
            t += np.dot(V[lp[0]], np.cross(V[lp[i]], V[lp[i + 1]])) / 6.0
    return t
def brep(e, extra):
    s = ifcopenshell.geom.settings(); s.set('use-world-coords', True); s.set('iterator-output', WR.SERIALIZED)
    for k, v in extra.items(): s.set(k, v)
    sh = ifcopenshell.geom.create_shape(s, e)
    d = sh.geometry.brep_data; fn = '/tmp/_tv_%d.brep' % os.getpid()
    (open(fn, 'wb') if isinstance(d, bytes) else open(fn, 'w')).write(d)
    x = TopoDS_Shape(); breptools.Read(x, fn, BRep_Builder())
    g = GProp_GProps(); brepgprop.VolumeProperties(x, g)
    return round(g.Mass() * 1e9, 1), BRepCheck_Analyzer(x).IsValid()
for gid in sys.argv[2:]:
    e = f.by_guid(gid)
    print('==', gid, e.is_a(), e.Name)
    for extra in ({}, {'boolean-attempt-2d': False}):
        try:
            print('  brep', extra, brep(e, extra))
        except Exception as ex:
            print('  brep', extra, 'ERR', ex)
        for mode in ('poly', 'tri'):
            s, _, m = v6.kernel_settings(mode)
            for k, v in extra.items(): s.set(k, v)
            try:
                sh = ifcopenshell.geom.create_shape(s, e)
                V, faces, iids = v6.kernel_geometry(sh.geometry, m)
                loops = [lp for fc in faces for lp in fc]
                print('  ', mode, extra, 'faces', len(faces), 'loops', len(loops), 'signed vol (all loops)', round(sv(V, loops), 1), 'outer only', round(sv(V, [fc[0] for fc in faces]), 1))
                rep = v6.Repair(2)
                bp = v6.build_part(v6.kernel_pieces(f, V, faces, iids), rep)
                if bp not in (None, 'corrupt'):
                    X, solids, surfaces, tags = bp
                    print('      build_part solids', len(solids), 'surfaces', len(surfaces), 'tags', sorted(tags), 'repair', dict(rep.stats))
            except Exception as ex:
                print('  ', mode, extra, 'ERR', ex)
