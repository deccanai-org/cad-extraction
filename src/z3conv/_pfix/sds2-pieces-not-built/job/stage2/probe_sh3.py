import sys, os
sys.path.insert(0, sys.argv[1])
import numpy as np, brep
from piece_table import read_pieces
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
MM = 25.4
W = '/work/agentwork/sds2-pieces-not-built/jobs/'
jn, sids = sys.argv[2].split(':')
P = read_pieces(W + jn)
for sid in [int(x) for x in sids.split(',')]:
    p = P[sid]
    V, F = brep.parse(open(os.path.join(W + jn, 'subm', str(sid)), 'rb').read())
    parts = brep.bodies(F)
    print(sid, p['name'], 'L W T wt', round(p['L'], 3), round(p['W'], 3), round(p['T'], 4), round(p['wt'], 2), 'nv nf', len(V), len(F), 'bodies', len(parts))
    for k, pf in enumerate(parts[:8]):
        used = sorted({i for f in pf for i in f})
        s = brep._solid(V, pf)
        vol = None; area = None
        if s is not None:
            g = GProp_GProps(); BRepGProp.VolumeProperties_s(s, g); vol = abs(g.Mass()) / MM ** 3
            g2 = GProp_GProps(); BRepGProp.SurfaceProperties_s(s, g2); area = g2.Mass() / MM ** 2
        print('   body', k, 'faces', len(pf), 'lo', np.round(V[used].min(0), 2).tolist(), 'hi', np.round(V[used].max(0), 2).tolist(),
              'solid', s is not None, 'vol_lb', None if vol is None else round(vol * 0.2836, 1), 'area', None if area is None else round(area, 1))
    sh = brep.solid(V, F)
    if sh is not None:
        g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); print('   solid() vol_lb', round(abs(g.Mass()) / MM ** 3 * 0.2836, 1), sh.ShapeType())
