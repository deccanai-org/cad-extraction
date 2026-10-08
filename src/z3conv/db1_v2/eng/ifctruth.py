"""Tekla-exported IFC -> per-element extrusion truth (axis ends in mm, frame, profile)."""
import ifcopenshell, ifcopenshell.util.placement as up, ifcopenshell.util.unit as uu, numpy as np, sys, pickle
def truth(path):
    f = ifcopenshell.open(path); sc = uu.calculate_unit_scale(f) * 1000
    out = []
    for e in f.by_type('IfcBuildingElement') + f.by_type('IfcElementAssembly')[:0]:
        if not e.Representation: continue
        M = np.array(up.get_local_placement(e.ObjectPlacement)); M[:3, 3] *= sc
        for r in e.Representation.Representations:
            for it in r.Items:
                while True:
                    if it.is_a('IfcMappedItem'): it = it.MappingSource.MappedRepresentation.Items[0]
                    elif it.is_a('IfcBooleanResult'): it = it.FirstOperand   # Tekla cut parts: clipping(extrusion, cut)
                    else: break
                if it.is_a('IfcExtrudedAreaSolid'):
                    P = np.array(up.get_axis2placement(it.Position)); P[:3, 3] *= sc
                    d = np.array(it.ExtrudedDirection.DirectionRatios); L = it.Depth * sc
                    G = M @ P; a = G[:3, 3]; b = a + G[:3, :3] @ d * L
                    pd = {k: v for k, v in it.SweptArea.get_info(recursive=False).items() if isinstance(v, (int, float, str))}
                    out.append(dict(R=G[:3, :3].copy(), guid=e.GlobalId, cls=e.is_a(), name=e.Name,
                                    prof=it.SweptArea.ProfileName, ptype=it.SweptArea.is_a(), pdims=pd, a=a, b=b, L=L))
    return out
if __name__ == '__main__':
    out = truth(sys.argv[1]); pickle.dump(out, open(sys.argv[1] + '.truth.pkl', 'wb')); print(len(out))
