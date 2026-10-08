#!/usr/bin/env python3
"""kernel-path diagnosis of one product: raw kernel faces -> repair steps -> components (closed/open, free edges).
usage: diag_kernel.py CONVERTER.py IFC GUID [poly|tri]"""
import sys, os, collections, importlib.util
spec = importlib.util.spec_from_file_location('v6', sys.argv[1]); V = importlib.util.module_from_spec(spec); spec.loader.exec_module(V)
import ifcopenshell, ifcopenshell.geom, numpy as np
f = ifcopenshell.open(sys.argv[2]); g = sys.argv[3]; mode = sys.argv[4] if len(sys.argv) > 4 else 'poly'
os.environ.setdefault('DEFLECTION', '0.005'); os.environ.setdefault('ANG_DEFLECTION', '0.6')
s, _, m = V.kernel_settings(mode)
p = f.by_guid(g)
sh = ifcopenshell.geom.create_shape(s, p)
Vk, faces, iids = V.kernel_geometry(sh.geometry, m)
print(p.is_a(), p.Name, 'kernel verts', len(Vk), 'faces', len(faces), 'items', collections.Counter(iids or []))
rep = V.Repair(2)
w = rep.weld(Vk); Q, inv = w; X = Q / 100.0
fs = rep.clean_faces(faces, inv, X)
nb, ba, bb = rep.boundary_count(fs, len(X)); print('after clean', len(fs), 'free edges', nb, dict(rep.stats))
fs = rep.dedup_faces(fs); nb, ba, bb = rep.boundary_count(fs, len(X)); print('after dedup', len(fs), 'free edges', nb, 'twins', len(rep.last_twins), dict(rep.stats))
fs2, nm = rep.sew(fs, X, rep.tol_sew); nb2, _, _ = rep.boundary_count(fs2, len(X)); print('sew merged', nm, 'free edges', nb2)
fs3, nt = rep.tjunctions(fs2, X); nb3, ba3, bb3 = rep.boundary_count(fs3, len(X)); print('tjunction inserted', nt, 'free edges', nb3)
for a, b in list(zip(ba3.tolist(), bb3.tolist()))[:8]:
    print('    free', X[a], X[b], round(float(np.linalg.norm(X[a] - X[b])), 3))
shs = rep.shells(fs3, X, 'solid')
for s_ in shs:
    A, B, F = rep.edge_arrays(s_.faces)
    key = np.minimum(A, B) * len(X) + np.maximum(A, B)
    u, c = np.unique(key, return_counts=True)
    print('  shell faces', len(s_.faces), 'closed', s_.closed, 'vol %.1f' % s_.vol, 'edge counts', dict(collections.Counter(c.tolist())), 'clearly_open', rep.clearly_open(s_.faces, X))
