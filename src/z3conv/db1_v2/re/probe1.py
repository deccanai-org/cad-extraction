import sys, json, collections, numpy as np
from db1dec import *
from guidmap import db1_guids, ifc_tags
db1, ifc, eng = sys.argv[1:4]
L = json.load(open('layouts.json')); VA = [v['layout'] for v in L.values() if v.get('layout')]
data = load(db1)
db, pts, cs, lay = decode(data, L[eng]['layout'], VA, False)
M = members(db, pts, cs, lay)
print('members', len(M), 'lay', {k: lay.get(k) for k in ('stride','poly_field','poly_stride','poly_field2','poly_stride2')})
seqs = {m['seq']: m for m in M}
G, info = db1_guids(data); f, T = ifc_tags(ifc)
for cls in ('IfcBeam', 'IfcPlate', 'IfcMechanicalFastener'):
    c = collections.Counter(); n = 0
    for g, e in T.items():
        if e.is_a() != cls or g not in G: continue
        n += 1; r = G[g]
        for fld in ('key', 'k25', 'k29', 'f13', 'f17'):
            if r[fld] in seqs: c[fld] += 1
            st = db.lookup_stride([r[fld]])[0]
            c[(fld, int(st))] += 1
    print(cls, n, sorted(c.items(), key=lambda x: -x[1])[:14])
