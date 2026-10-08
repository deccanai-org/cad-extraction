#!/usr/bin/env python3
"""plan1.py PIPE JOB GR4D.json OUT.json : plan-outline area of every grating piece vs the record's W x L (validation probe)."""
import sys, os, re, json, collections
import numpy as np
PIPE, job, g4, outp = sys.argv[1:5]
sys.path.insert(0, os.path.join(PIPE, 'decode'))
from piece_table import read_pieces, slot_size, LAYOUTS
import brep, grating as G
from shapely.geometry import Polygon
from shapely.ops import unary_union
b = open(os.path.join(job, 'subm', 'subm_idx'), 'rb').read()
S = LAYOUTS[slot_size(b)]['slot']
res = []
for d in json.load(open(g4))['pieces']:
    k = d['sid']; fp = os.path.join(job, 'subm', str(k))
    if not os.path.exists(fp) or not d.get('slot'):
        continue
    r = brep.parse(open(fp, 'rb').read())
    if r is None: continue
    V, F = r[0], brep.conform(r[0], r[1])
    parts = brep.bodies(F)
    markers = [brep.loops_of(P[0])[0] for P in parts if len(P) == 1 and len(brep.loops_of(P[0])) == 1]
    if markers:
        n = G._normal(V[markers[0]])[1]
    else:
        allv = V[sorted({i for f in F for i in f})]; n = np.eye(3)[int(np.argmin(np.ptp(allv, 0)))]
    u = np.cross(n, [1.0, 0, 0] if abs(n[0]) < 0.9 else [0, 1.0, 0]); u /= np.linalg.norm(u); w = np.cross(n, u)
    polys = []
    for f in F:
        ls = brep.loops_of(f)
        if not ls or len(ls[0]) < 3: continue
        c, nn = G._normal(V[ls[0]])
        if nn is None or abs(nn @ n) < 0.9: continue
        try:
            pg = Polygon([(q @ u, q @ w) for q in V[ls[0]]]).buffer(0)
        except Exception:
            continue
        if pg.area > 0: polys.append(pg)
    s = d['slot']; rr = max(s['bar_spacing'], s['cross_spacing']) / 2 + 0.02
    U = unary_union(polys)
    A = U.buffer(rr, 4).buffer(-rr, 4).area
    WL = s['width'] * s['length']
    res.append(dict(sid=k, name=d['name'], placed=d['placed'], ok=d.get('ok'), cut=d.get('cut_from_stock', False),
                    r=d.get('weight_ratio'), plan_ratio=round(A / WL, 4), cells=d.get('cells'), bodies=d.get('bodies'),
                    cb=d.get('cross_bars'), why=d.get('why', '')[:80]))
json.dump(res, open(outp, 'w'))
print(job, len(res))
