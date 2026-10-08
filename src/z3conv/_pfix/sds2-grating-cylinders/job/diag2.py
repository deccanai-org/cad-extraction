import sys, os, collections
import numpy as np
sys.path.insert(0, sys.argv[1] + '/decode')
import brep, to_step2 as T2
from piece_table import read_pieces
job, sid = sys.argv[2], int(sys.argv[3])
p = read_pieces(job)[sid]; print(p)
V, F = brep.parse(open(os.path.join(job, 'subm', str(sid)), 'rb').read())
print('faces', len(F), 'multi-loop faces', sum(len(brep.loops_of(f)) > 1 for f in F))
for tol in (0.002, 0.003, 0.005, 0.01):
    F2 = T2._merge_vertices(V, F, tol)
    if F2 is None: print(tol, 'merge refused'); continue
    E = collections.Counter()
    for f in F2:
        for l in brep.loops_of(f):
            for a, b in zip(l, l[1:] + l[:1]):
                if a != b: E[(min(a, b), max(a, b))] += 1
    F3 = brep.conform(V, F2)
    E3 = collections.Counter()
    for f in F3:
        for l in brep.loops_of(f):
            for a, b in zip(l, l[1:] + l[:1]):
                if a != b: E3[(min(a, b), max(a, b))] += 1
    sh = brep.solid(V, F2)
    vol = None
    if sh is not None:
        from OCP.GProp import GProp_GProps
        from OCP.BRepGProp import BRepGProp
        g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); vol = abs(g.Mass()) / 25.4 ** 3 * 0.2836 / p['wt']
    print(tol, 'faces', len(F2), 'edge use', dict(collections.Counter(E.values())), 'after conform', dict(collections.Counter(E3.values())), 'solid', sh is not None, 'wt ratio', vol)
