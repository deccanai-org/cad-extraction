#!/usr/bin/env python3
"""diag_shell.py IFC STEPID - faces of an IfcFacetedBrep (loop sizes) and its non-2-manifold edges with coordinates"""
import sys, collections
import numpy as np
import ifcopenshell
f = ifcopenshell.open(sys.argv[1])
b = f.by_id(int(sys.argv[2]))
sh = b.Outer if b.is_a('IfcFacetedBrep') else b
loops = []
for fc in sh.CfsFaces:
    for bd in fc.Bounds:
        ids = [p.id() for p in bd.Bound.Polygon]
        if not bd.Orientation:
            ids = ids[::-1]
        loops.append((bd.is_a(), ids))
print('faces', len(sh.CfsFaces), 'loop sizes', collections.Counter(len(l) for _, l in loops), 'bounds', collections.Counter(t for t, _ in loops))
c = collections.Counter()
for _, lp in loops:
    for i in range(len(lp)):
        c[tuple(sorted((lp[i], lp[(i + 1) % len(lp)])))] += 1
bad = [k for k, n in c.items() if n != 2]
P = {}
for _, lp in loops:
    for i in lp:
        P[i] = f.by_id(i).Coordinates
print('distinct point ids', len(P), 'distinct coords', len(set(tuple(round(x, 9) for x in v) for v in P.values())))
for k in bad[:8]:
    print('edge', k, c[k], P[k[0]], P[k[1]])
for t, lp in loops[:40]:
    print(t[3:], len(lp), [tuple(round(x * 304.8, 2) for x in P[i]) for i in lp][:6])
