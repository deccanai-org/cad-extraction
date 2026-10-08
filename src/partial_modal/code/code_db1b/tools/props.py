#!/usr/bin/env python3
"""part_properties.jsonl: every property set value of every part (and of its assembly), as exported by the authoring
tool. usage: props.py MODEL.ifc SCHEDULE_DIR"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract
f = extract.open_ifc(sys.argv[1])
asm = {}
for rel in f.by_type('IfcRelAggregates'):
    if rel.RelatingObject.is_a('IfcElementAssembly'):
        for o in rel.RelatedObjects:
            asm[o.id()] = rel.RelatingObject
def qto(e):
    out = {}
    for rel in getattr(e, 'IsDefinedBy', None) or []:
        if rel.is_a('IfcRelDefinesByProperties') and rel.RelatingPropertyDefinition.is_a('IfcElementQuantity'):
            q = rel.RelatingPropertyDefinition
            for x in q.Quantities:
                v = next((getattr(x, a) for a in ('LengthValue', 'AreaValue', 'VolumeValue', 'WeightValue', 'CountValue') if hasattr(x, a)), None)
                if v is not None:
                    out[q.Name + '.' + x.Name] = v
    return out
n = 0
with open(os.path.join(sys.argv[2], 'part_properties.jsonl'), 'w') as fh:
    for p in f.by_type('IfcProduct'):
        if not getattr(p, 'GlobalId', None) or p.is_a('IfcOpeningElement') or p.is_a('IfcSpatialStructureElement'):
            continue
        a = asm.get(p.id())
        rec = {'part_id': p.GlobalId, 'ifc_class': p.is_a(), 'name': p.Name, 'object_type': getattr(p, 'ObjectType', None), 'tag': getattr(p, 'Tag', None),
               'material': extract.material_of(p), 'properties': {k: (v if isinstance(v, (int, float, str, bool)) or v is None else str(v)) for k, v in extract.psets(p).items()},
               'quantities': qto(p)}
        if a is not None:
            rec['assembly'] = {'id': a.GlobalId, 'name': a.Name, 'tag': a.Tag, 'properties': {k: (v if isinstance(v, (int, float, str, bool)) or v is None else str(v)) for k, v in extract.psets(a).items()}}
        fh.write(json.dumps(rec, default=str) + '\n')
        n += 1
print(n, 'parts with properties (length unit to mm:', extract.unit_factors(f)[0], ')')
