#!/usr/bin/env python3
"""open faceted part: boundary loops after v6 repair - size, planarity, nearest opposite boundary distance (seam gap)
usage: diag_open.py CONVERTER.py IFC GUID"""
import sys, os, collections, importlib.util
spec = importlib.util.spec_from_file_location('v6', sys.argv[1]); V = importlib.util.module_from_spec(spec); spec.loader.exec_module(V)
import ifcopenshell, ifcopenshell.util.unit, numpy as np
f = ifcopenshell.open(sys.argv[2]); g = sys.argv[3]
sc = ifcopenshell.util.unit.calculate_unit_scale(f) * 1000
tc = V.Transcoder(f, sc)
p = f.by_guid(g); items, rid = V.body_items(p)
pieces = tc.product(p, items)
print(p.is_a(), p.Name, [it.is_a() for it in items], 'pieces', [(pc.role, len(pc.faces)) for pc in pieces] if pieces else None)
if not pieces:
    sys.exit()
for pc in pieces:
    rep = V.Repair(2)
    w = rep.weld(pc.V); Q, inv = w; X = Q / 100.0
    fs = rep.clean_faces(pc.faces, inv, X); fs = rep.dedup_faces(fs)
    fs, nm = rep.sew(fs, X, rep.tol_sew); fs, nt = rep.tjunctions(fs, X)
    nb, ba, bb = rep.boundary_count(fs, len(X))
    bbx = X[np.unique([i for fc in fs for lp in fc for i in lp])]
    print(' piece', pc.role, 'faces', len(fs), 'free edges', nb, 'sewn', nm, 'tj', nt, 'size', (bbx.max(0) - bbx.min(0)).round(1), dict(rep.stats))
    if not nb:
        continue
    # chain boundary edges into loops
    nxt = collections.defaultdict(list)
    for a, b in zip(ba.tolist(), bb.tolist()):
        nxt[a].append(b)
    seen = set(); loops = []
    for a0 in list(nxt):
        for b0 in list(nxt[a0]):
            if (a0, b0) in seen: continue
            lp = [a0]; a, b = a0, b0
            while (a, b) not in seen:
                seen.add((a, b)); lp.append(b)
                cand = [c for c in nxt[b] if (b, c) not in seen]
                if not cand: break
                a, b = b, cand[0]
            loops.append(lp)
    for lp in loops[:10]:
        P = X[lp]
        per = float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())
        n = V.newell(P); area = np.linalg.norm(n) / 2
        nh = n / (np.linalg.norm(n) + 1e-300); dev = float(np.abs((P - P.mean(0)) @ nh).max())
        # seam width: max over loop vertices of min distance to the other loop vertices not adjacent
        print('   loop verts', len(lp), 'perimeter %.2f' % per, 'area %.2f' % area, 'planar-dev %.3f' % dev, 'width~%.3f' % (2 * area / per if per else 0))
