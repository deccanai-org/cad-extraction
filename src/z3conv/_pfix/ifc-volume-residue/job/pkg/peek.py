#!/usr/bin/env python3
"""peek.py IFC ID... - product summary: class, name, body items (deep), openings"""
import sys
import ifcopenshell
f = ifcopenshell.open(sys.argv[1])
for i in sys.argv[2:]:
    e = f.by_id(int(i)) if i.isdigit() else f.by_guid(i)
    print('==', e.id(), e.is_a(), e.GlobalId, e.Name, 'openings', len(getattr(e, 'HasOpenings', None) or []))
    for r in e.Representation.Representations:
        print('  rep', r.RepresentationIdentifier, r.RepresentationType, len(r.Items))
        for it in r.Items[:3]:
            tr = list(f.traverse(it))
            kinds = {}
            for x in tr:
                kinds[x.is_a()] = kinds.get(x.is_a(), 0) + 1
            print('    item', str(it)[:160], 'traverse', len(tr), sorted(kinds.items(), key=lambda kv: -kv[1])[:8])
