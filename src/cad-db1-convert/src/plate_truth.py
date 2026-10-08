"""IfcPlate truth: global outline vertices (mm), thickness, extrusion normal, profile name."""
import ifcopenshell, ifcopenshell.util.placement as up, ifcopenshell.util.unit as uu, numpy as np, sys, pickle
def plates(path):
    f = ifcopenshell.open(path); sc = uu.calculate_unit_scale(f) * 1000; out = []
    for e in f.by_type('IfcPlate') + f.by_type('IfcBeam') + f.by_type('IfcMember') + f.by_type('IfcColumn'):
        if not e.Representation: continue
        M = np.array(up.get_local_placement(e.ObjectPlacement)); M[:3, 3] *= sc
        for r in e.Representation.Representations:
            for it in r.Items:
                while True:
                    if it.is_a('IfcMappedItem'): it = it.MappingSource.MappedRepresentation.Items[0]
                    elif it.is_a('IfcBooleanResult'): it = it.FirstOperand
                    else: break
                if not it.is_a('IfcExtrudedAreaSolid'): continue
                pr = it.SweptArea
                if not pr.is_a('IfcArbitraryClosedProfileDef'): continue
                crv = pr.OuterCurve
                if not crv.is_a('IfcPolyline'): continue
                P = np.array(up.get_axis2placement(it.Position)); P[:3, 3] *= sc; G = M @ P
                loc = [np.array(list(p.Coordinates) + [0.0] * (3 - len(p.Coordinates))) * sc for p in crv.Points]
                glob = [G[:3, :3] @ v + G[:3, 3] for v in loc]
                d = np.array(it.ExtrudedDirection.DirectionRatios)
                out.append(dict(guid=e.GlobalId, cls=e.is_a(), prof=pr.ProfileName, pts=np.array(glob), t=it.Depth * sc,
                                n=G[:3, :3] @ d, R=G[:3, :3].copy(), loc=np.array(loc)))
    return out
if __name__ == '__main__':
    o = plates(sys.argv[1]); pickle.dump(o, open(sys.argv[1] + '.plates.pkl', 'wb'))
    import collections; print(len(o), collections.Counter(p['cls'] for p in o), collections.Counter(len(p['pts']) for p in o).most_common(6))
