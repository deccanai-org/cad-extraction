"""inspect_part.py IFC PARTS_JSON_GZ PID [PID...] : dump a written part's body + every cut operand (bolt hole vs Tekla cut part)
in the part's local frame (extrusion axis = local Z)."""
import sys, json, gzip, numpy as np, ifcopenshell
ifc, plp = sys.argv[1], sys.argv[2]
pids = [int(x) for x in sys.argv[3:]]
f = ifcopenshell.open(ifc)
pl = json.load(gzip.open(plp, 'rt'))
by = {r[0]: r for r in pl}


def ax(p):
    o = np.array(p.Location.Coordinates, float)
    z = np.array(p.Axis.DirectionRatios, float) if p.Axis else np.array([0, 0, 1.])
    x = np.array(p.RefDirection.DirectionRatios, float) if p.RefDirection else np.array([1., 0, 0])
    return o, z, x


def prof_s(pr):
    t = pr.is_a()
    if t == 'IfcCircleProfileDef': return f'{pr.ProfileName} CIRC r={pr.Radius:g}'
    if t == 'IfcRectangleProfileDef': return f'{pr.ProfileName} RECT {pr.XDim:g}x{pr.YDim:g}'
    if t == 'IfcArbitraryClosedProfileDef':
        pts = [tuple(round(c, 2) for c in p.Coordinates) for p in pr.OuterCurve.Points]
        return f'{pr.ProfileName} ARB {pts}'
    return f'{pr.ProfileName} {t} ' + ' '.join(f'{a}={getattr(pr, a)}' for a in pr.get_info().keys() if a not in ('id', 'type', 'ProfileType', 'ProfileName', 'Position'))[:300]


for pid in pids:
    r = by[pid]; print('== part', r)
    e = f.by_guid(r[5])
    rep = e.Representation.Representations[0].Items[0]
    pl0 = e.ObjectPlacement.RelativePlacement
    print('   placement', [list(np.round(v, 3)) for v in ax(pl0)])
    ops = []
    x = rep
    while x.is_a('IfcBooleanResult'):
        ops.append(x.SecondOperand); x = x.FirstOperand
    print('   base', prof_s(x.SweptArea), 'depth', x.Depth)
    for k, c in enumerate(reversed(ops)):
        o, z, xx = ax(c.Position)
        print(f'   cut{k}', prof_s(c.SweptArea), 'depth', round(c.Depth, 3), 'o', list(np.round(o, 3)), 'z', list(np.round(z, 5)), 'x', list(np.round(xx, 5)))
