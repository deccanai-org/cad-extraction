#!/usr/bin/env python3
"""verify_recovered.py DEV3_WD DEV3P_WD CONV_P - parts missing in dev3 (empty kernel boolean) and present in dev3p:
STEP volume S vs the body without openings X0 and the openings' own volumes (repaired shells, kernel mesh):
removed = X0 - S must be > 0 and <= sum(V_open); also the sidecar record (level, tags) of the recovered part"""
import sys, os, json, gzip, importlib.util
import numpy as np
import ifcopenshell, ifcopenshell.geom
d3, d3p, conv = sys.argv[1:4]
spec = importlib.util.spec_from_file_location('v6', conv)
v6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)
v6.np = np
miss = [x[0] for x in json.load(open(os.path.join(d3, 'out.step.stats.json'))).get('parts_without_geometry_examples') or []]
stp = {}
for l in gzip.open(os.path.join(d3p, 'step_parts.jsonl.gz'), 'rt'):
    p = json.loads(l)
    if p.get('pid'):
        stp.setdefault(p['pid'], p)
side = {p['gid']: p for p in json.load(open(os.path.join(d3p, 'out.step.parts.json')))['parts']}
f = ifcopenshell.open(os.path.join(d3p, 'in.bin'))
def mvol(e, noop=False):
    s, _, m = v6.kernel_settings('tri')
    if noop:
        s.set('disable-opening-subtractions', True)
    sh = ifcopenshell.geom.create_shape(s, e)
    V, faces, _ = v6.kernel_geometry(sh.geometry, m)
    t = 0.0
    for fc in faces:
        lp = fc[0]
        for i in range(1, len(lp) - 1):
            t += np.dot(V[lp[0]], np.cross(V[lp[i]], V[lp[i + 1]])) / 6.0
    return t
prods = [f.by_guid(g) for g in miss]
x0 = {p.GlobalId: mvol(p, True) for p in prods}
v6.repair_opening_shells(prods)          # same in-memory repair as the converter
for p in prods:
    vo = [abs(mvol(rel.RelatedOpeningElement)) for rel in p.HasOpenings]
    S = (stp.get(p.GlobalId) or {}).get('volume')
    sd = side.get(p.GlobalId) or {}
    rem = x0[p.GlobalId] - S if S else None
    print(json.dumps({'gid': p.GlobalId, 'name': p.Name, 'openings': len(vo), 'X0': round(x0[p.GlobalId], 1), 'S': S,
                      'removed': round(rem, 1) if rem is not None else None, 'sum_open': round(sum(vo), 1),
                      'removed_over_open': round(rem / sum(vo), 4) if rem and sum(vo) else None,
                      'level': sd.get('level'), 'tags': sd.get('tags'), 'solids': sd.get('solids'), 'valid': (stp.get(p.GlobalId) or {}).get('valid')}))
