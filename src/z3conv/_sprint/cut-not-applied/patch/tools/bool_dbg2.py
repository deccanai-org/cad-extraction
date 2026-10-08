import sys, ifcopenshell, numpy as np
f = ifcopenshell.open(sys.argv[1]); e = f.by_guid(sys.argv[2])
rep = [r for r in e.Representation.Representations if r.RepresentationIdentifier == 'Body'][0]
def walk(x):
    if x.is_a('IfcBooleanResult'):
        walk(x.FirstOperand); s = x.SecondOperand
        if s.SweptArea.is_a('IfcArbitraryClosedProfileDef'):
            pts = [p.Coordinates for p in s.SweptArea.OuterCurve.Points]
            P = np.array(pts); print('cutter', s.SweptArea.ProfileName, 'npts', len(pts), 'bbox', np.round(P.min(0), 1).tolist(), np.round(P.max(0), 1).tolist(), 'pos', [round(c, 1) for c in s.Position.Location.Coordinates],
                                    'z', s.Position.Axis.DirectionRatios if s.Position.Axis else None, 'x', s.Position.RefDirection.DirectionRatios if s.Position.RefDirection else None)
            print('    ', [tuple(round(c, 1) for c in p) for p in pts][:10])
    else:
        print('base', x.SweptArea.is_a(), x.SweptArea.ProfileName, x.Depth)
for it in rep.Items: walk(it)
