#!/usr/bin/env python3
"""diag_open2.py IFC GID... - per opening: mapped transform determinant, faceted shell signed volume (local + mapped),
open edges, and kernel volume of the opening element itself (tri mesh)"""
import sys, os, importlib.util, collections
import numpy as np
import ifcopenshell, ifcopenshell.geom, ifcopenshell.util.placement as up
spec = importlib.util.spec_from_file_location('v6', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ifc2step6_dev3.py'))
v6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)
f = ifcopenshell.open(sys.argv[1])
def sv(P, faces):
    t = 0.0
    for lp in faces:
        for i in range(1, len(lp) - 1):
            t += np.dot(P[lp[0]], np.cross(P[lp[i]], P[lp[i + 1]])) / 6.0
    return t
def shell(sh):
    raw = []; idx = {}; faces = []
    for fc in sh.CfsFaces:
        for b in fc.Bounds:
            ids = []
            for p in b.Bound.Polygon:
                j = idx.get(p.id())
                if j is None:
                    j = len(raw); raw.append(p.Coordinates); idx[p.id()] = j
                ids.append(j)
            if not b.Orientation:
                ids = ids[::-1]
            faces.append(ids)
    return np.array(raw, float), faces
def edges(faces):
    c = collections.Counter()
    for lp in faces:
        for i in range(len(lp)):
            a, b = lp[i], lp[(i + 1) % len(lp)]
            c[(a, b)] += 1
    und = collections.Counter()
    for (a, b), n in c.items():
        und[tuple(sorted((a, b)))] += n
    return sum(1 for k, n in und.items() if n != 2), sum(1 for (a, b), n in c.items() if c.get((b, a), 0) != n)
for gid in sys.argv[2:]:
    e = f.by_guid(gid)
    print('==', gid, e.Name, 'openings', len(e.HasOpenings))
    for o in e.HasOpenings:
        op = o.RelatedOpeningElement
        P = np.array(up.get_local_placement(op.ObjectPlacement))
        for rep in op.Representation.Representations:
            for it in rep.Items:
                M = P
                src = it
                if it.is_a('IfcMappedItem'):
                    T = np.array(up.get_mappeditem_transformation(it))
                    M = P @ T
                    src = it.MappingSource.MappedRepresentation.Items[0]
                    tr = it.MappingTarget
                    print('  map target', tr, 'axis1', tr.Axis1.DirectionRatios if tr.Axis1 else None, 'axis2', tr.Axis2.DirectionRatios if tr.Axis2 else None, 'axis3', tr.Axis3.DirectionRatios if getattr(tr, 'Axis3', None) else None)
                    print('  map origin', it.MappingSource.MappingOrigin)
                det = np.linalg.det(M[:3, :3])
                if src.is_a('IfcFacetedBrep'):
                    X, faces = shell(src.Outer)
                    vl = sv(X, faces)
                    Xw = X @ M[:3, :3].T + M[:3, 3]
                    vw = sv(Xw, faces)
                    ne, nd = edges(faces)
                    print('  opening', op.Name, src.is_a(), 'faces', len(faces), 'det', round(det, 6), 'vol local', round(vl, 9), 'vol world', round(vw, 9), 'nonmanifold/open edges', ne, 'inconsistent dir edges', nd)
                else:
                    print('  opening', op.Name, src, 'det', round(det, 6))
        try:
            s, _, m = v6.kernel_settings('tri')
            sh = ifcopenshell.geom.create_shape(s, op)
            V, faces, iids = v6.kernel_geometry(sh.geometry, m)
            print('   kernel opening tri: verts', len(V), 'faces', len(faces), 'meshvol mm3', round(sv(V, [fc[0] for fc in faces]), 1))
        except Exception as ex:
            print('   kernel opening ERR', ex)
