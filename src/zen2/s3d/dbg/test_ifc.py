import sys, json, gzip, time, collections
sys.path.insert(0, '/Users/dhiren/Downloads/Deccan/zen2/s3d/src')
import numpy as np, ifcopenshell, ifcopenshell.geom
import ifcgen
Js = [json.load(gzip.open(p)) for p in sys.argv[1:]]
pts = np.array([q['xyz'] for J in Js for C in J['components'] for q in C['ports'] if q['xyz']])
origin = np.round(pts.mean(0) / 10) * 10
W = ifcgen.IfcW('test', origin, 'test-area')
for J in Js:
    print(J['name'], ifcgen.add_pipeline(W, J))
out = '/Users/dhiren/Downloads/Deccan/zen2/s3d/dbg/ifc/test.ifc'
W.write(out)
f = ifcopenshell.open(out)
s = ifcopenshell.geom.settings(); s.set('use-world-coords', True)
it = ifcopenshell.geom.iterator(s, f, 4)
bad = []; n = 0; bb = {}
if it.initialize():
    while True:
        sh = it.get(); n += 1
        v = np.array(sh.geometry.verts).reshape(-1, 3)
        e = f.by_guid(sh.guid)
        bb[e.Tag] = (v.min(0) + origin, v.max(0) + origin, e.is_a(), len(sh.geometry.faces) // 3)
        if not it.next(): break
print('elements with geometry', n, 'of', len(f.by_type('IfcElement')))
# check: every port point lies inside (or on) its element's bbox (tolerance 2 mm)
comp = {C['oid']: C for J in Js for C in J['components']}
miss = collections.Counter(); tot = 0
for oid, (lo, hi, cls, nt) in bb.items():
    C = comp.get(oid)
    if not C: continue
    for q in C['ports']:
        if not q['xyz']: continue
        tot += 1
        p = np.array(q['xyz'])
        if ((p < lo - 0.002) | (p > hi + 0.002)).any():
            miss[C['pcf_type']] += 1
print('port points inside element bbox:', tot - sum(miss.values()), '/', tot, 'outside by type', dict(miss))
tri = collections.Counter(); 
for oid, (lo, hi, cls, nt) in bb.items(): tri[cls] += nt
print('triangles by class', dict(tri))
import os; print('ifc bytes', os.path.getsize(out))
