#!/usr/bin/env python3
"""diag_part.py IFC GID [GID...] - representation, openings, kernel volumes (with / without openings), and what dev3's
build_part makes of the kernel polyhedral output for one product"""
import sys, os, json, importlib.util
import numpy as np
import ifcopenshell, ifcopenshell.geom
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('v6', os.environ.get('CONVPY', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ifc2step6_dev3.py')))
v6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)
v6.np = np
f = ifcopenshell.open(sys.argv[1])
for gid in sys.argv[2:]:
    e = f.by_guid(gid)
    print('=====', e)
    items, rid = v6.body_items(e)
    print('rid', rid, 'items', [str(it)[:300] for it in items])
    for it in items:
        if it.is_a('IfcMappedItem'):
            for si in it.MappingSource.MappedRepresentation.Items:
                print('  mapped src', str(si)[:300])
                for x in f.traverse(si)[:40]:
                    if x.is_a('IfcProfileDef') or x.is_a('IfcBooleanResult') or x.is_a('IfcHalfSpaceSolid'):
                        print('     ', str(x)[:300])
        else:
            for x in f.traverse(it)[:60]:
                if x.is_a('IfcProfileDef') or x.is_a('IfcBooleanResult') or x.is_a('IfcHalfSpaceSolid') or x.is_a('IfcExtrudedAreaSolid'):
                    print('     ', str(x)[:300])
    for o in (getattr(e, 'HasOpenings', None) or []):
        op = o.RelatedOpeningElement
        oi, _ = v6.body_items(op)
        print('  opening', op.GlobalId, [str(x)[:200] for x in (oi or [])])
        for x in (oi or []):
            for y in f.traverse(x)[:30]:
                if y.is_a('IfcProfileDef') or y.is_a('IfcExtrudedAreaSolid'):
                    print('       ', str(y)[:250])
    for mode in ('poly', 'tri'):
        for noop in (False, True):
            s, _, m = v6.kernel_settings(mode)
            if noop:
                s.set('disable-opening-subtractions', True)
            try:
                sh = ifcopenshell.geom.create_shape(s, e)
                V, faces, iids = v6.kernel_geometry(sh.geometry, m)
                rep = v6.Repair(2)
                pieces = v6.kernel_pieces(f, V, faces, iids)
                vol_mesh = None
                try:
                    allf = [lp for fc in faces for lp in fc[:1]]
                except Exception:
                    pass
                bp = v6.build_part(pieces, rep)
                info = None
                if bp is None or bp == 'corrupt':
                    info = bp
                else:
                    X, solids, surfaces, tags = bp
                    info = {'solids': len(solids), 'surfaces': len(surfaces), 'tags': sorted(tags), 'vol': [round(getattr(s_, 'vol', 0) or 0, 1) for s_ in solids][:10]}
                print('  kernel', mode, 'noopen' if noop else 'open', 'verts', len(V), 'faces', len(faces), 'iids', sorted(set(iids or []))[:6], '->', info, dict(rep.stats))
            except Exception as ex:
                print('  kernel', mode, noop, 'ERR', type(ex).__name__, str(ex)[:200])
