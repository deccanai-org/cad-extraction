"""mini_part.py IN.ifc GUID OUT_PREFIX : (ifcopenshell 0.8.4) one element copied into a fresh IFC (project + units kept) in variants:
none (as built) | holes (bolt holes dropped) | cuts (Tekla cut parts dropped) | all | op<k> (only operand k dropped);
prints json {variants: {name: path}, operands: [{k, hole, profile, depth, origin, axis}], base: profile}"""
import sys, json, ifcopenshell
src, guid, pre = sys.argv[1], sys.argv[2], sys.argv[3]
f = ifcopenshell.open(src)
e = f.by_guid(guid)
proj = f.by_type('IfcProject')[0]


def chain(rep_item):
    ops = []; x = rep_item
    while x.is_a('IfcBooleanResult'):
        ops.append(x.SecondOperand); x = x.FirstOperand
    return x, ops[::-1]


rep0 = e.Representation.Representations[0]
base, ops = chain(rep0.Items[0])
is_hole = lambda o: (getattr(o, 'SweptArea', None) is not None and (o.SweptArea.ProfileName or '').startswith('BOLT_HOLE'))
info = {'name': e.Name, 'cls': e.is_a(), 'base': base.is_a() + ':' + (getattr(getattr(base, 'SweptArea', None), 'ProfileName', '') or ''),
        'operands': [], 'variants': {}}
for k, o in enumerate(ops):
    d = {'k': k, 'hole': is_hole(o), 'type': o.is_a()}
    try:
        d['profile'] = o.SweptArea.ProfileName; d['ptype'] = o.SweptArea.is_a(); d['depth'] = o.Depth
        p = o.Position
        d['origin'] = list(p.Location.Coordinates); d['axis'] = list(p.Axis.DirectionRatios) if p.Axis else [0, 0, 1]
        if o.SweptArea.is_a('IfcCircleProfileDef'): d['r'] = o.SweptArea.Radius
    except Exception:
        pass
    info['operands'].append(d)
V = {'none': set(), 'holes': {k for k, o in enumerate(ops) if is_hole(o)}, 'cuts': {k for k, o in enumerate(ops) if not is_hole(o)}, 'all': set(range(len(ops)))}
if len(ops) <= 14:
    for k in range(len(ops)):
        V[f'op{k}'] = {k}
done = set()
for nm, kill in V.items():
    key = tuple(sorted(kill))
    if key in done and nm not in ('none',):
        continue
    done.add(key)
    g = ifcopenshell.file(schema=f.schema)
    g.add(proj)
    e2 = g.add(e)
    rep = e2.Representation.Representations[0]
    b2, ops2 = chain(rep.Items[0])
    solid = b2
    for k, o in enumerate(ops2):
        if k not in kill:
            solid = g.createIfcBooleanResult('DIFFERENCE', solid, o)
    rep.Items = [solid]
    rep.RepresentationType = 'CSG' if solid.is_a('IfcBooleanResult') else ('SweptSolid' if solid.is_a('IfcExtrudedAreaSolid') else rep.RepresentationType)
    p = f'{pre}_{nm}.ifc'; g.write(p); info['variants'][nm] = p
print(json.dumps(info))
