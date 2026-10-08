"""Tekla IFC export -> per-bolt truth. Each IfcMechanicalFastener is one bolt group ('Bolt assembly', Tag 'ID<guid>');
its Body is one IfcMappedItem per bolt. Shank = the extrusion whose depth == NominalLength (falls back to the longest
circle extrusion). -> list of dict(guid, d, L, start(world mm), axis(world), psets, hole)"""
import numpy as np, ifcopenshell, ifcopenshell.util.placement as up, ifcopenshell.util.unit as uu, ifcopenshell.util.element as ue

def _op(t):
    """IfcCartesianTransformationOperator3D -> 4x4"""
    M = np.eye(4)
    o = np.array(t.LocalOrigin.Coordinates, float); o = np.pad(o, (0, 3 - len(o)))
    a1 = np.array(t.Axis1.DirectionRatios, float) if t.Axis1 else np.array([1., 0, 0])
    a3 = np.array(t.Axis3.DirectionRatios, float) if getattr(t, 'Axis3', None) else np.array([0., 0, 1])
    a1 = a1 / np.linalg.norm(a1); a3 = a3 / np.linalg.norm(a3)
    a2 = np.array(t.Axis2.DirectionRatios, float) if t.Axis2 else np.cross(a3, a1)
    a2 = a2 / np.linalg.norm(a2)
    s = t.Scale if t.Scale else 1.0
    M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = a1 * s, a2 * s, a3 * s, o
    return M

def bolts(path, with_groups=False):
    f = ifcopenshell.open(path); sc = uu.calculate_unit_scale(f) * 1000.0
    out = []; groups = []
    for e in f.by_type('IfcMechanicalFastener'):
        tag = (e.Tag or '')
        g = tag[2:38].upper() if tag.startswith('ID') else None
        d = float(e.NominalDiameter or 0) * (sc if sc != 1000.0 else 1.0); L = float(e.NominalLength or 0) * (sc if sc != 1000.0 else 1.0)
        ps = ue.get_psets(e).get('Tekla Bolt', {})
        P = np.array(up.get_local_placement(e.ObjectPlacement)); P[:3, 3] *= sc
        rec = dict(guid=g, d=d, L=L, pset=ps, bolts=[])
        if not e.Representation: groups.append(rec); continue
        for r in e.Representation.Representations:
            if r.RepresentationIdentifier != 'Body': continue
            for it in r.Items:
                if not it.is_a('IfcMappedItem'): continue
                T = _op(it.MappingTarget); T[:3, 3] *= sc
                O = np.array(up.get_axis2placement(it.MappingSource.MappingOrigin)); O[:3, 3] *= sc
                best = None
                for x in it.MappingSource.MappedRepresentation.Items:
                    if not x.is_a('IfcExtrudedAreaSolid'): continue
                    dep = x.Depth * sc
                    circ = x.SweptArea.is_a('IfcCircleProfileDef')
                    sc_ = (abs(dep - L) < 0.05 and circ, circ, dep)
                    if best is None or sc_ > best[0]: best = (sc_, x)
                if best is None: continue
                x = best[1]
                Q = np.array(up.get_axis2placement(x.Position)); Q[:3, 3] *= sc
                W = P @ T @ O @ Q
                dirl = np.array(x.ExtrudedDirection.DirectionRatios, float); dirl /= np.linalg.norm(dirl)
                ax = W[:3, :3] @ dirl; ax /= np.linalg.norm(ax)
                st = W[:3, 3]
                rec['bolts'].append(dict(start=st, axis=ax, depth=x.Depth * sc, r=x.SweptArea.Radius * sc if x.SweptArea.is_a('IfcCircleProfileDef') else None))
        groups.append(rec)
        for b in rec['bolts']: out.append(dict(guid=g, d=d, L=L, start=b['start'], axis=b['axis'], shank=b['depth'], hole=ps.get('Bolt hole diameter'),
                                               slot_x=ps.get('Slotted hole x'), slot_y=ps.get('Slotted hole y')))
    return (out, groups) if with_groups else out

if __name__ == '__main__':
    import sys, collections
    B, G = bolts(sys.argv[1], True)
    print('groups', len(G), 'bolts', len(B), collections.Counter(len(g['bolts']) for g in G).most_common(8))
    print(B[0]); print(collections.Counter((round(b['d'], 2), round(b['L'], 1)) for b in B).most_common(8))
    print('slotted', sum(1 for g in G if (g['pset'].get('Slotted hole x') or 0) or (g['pset'].get('Slotted hole y') or 0)))
