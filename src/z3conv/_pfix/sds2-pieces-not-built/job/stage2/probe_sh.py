import sys, os, collections
sys.path.insert(0, sys.argv[1])
import numpy as np
import brep
from piece_table import read_pieces, kind
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
MM = 25.4
W = '/work/agentwork/sds2-pieces-not-built/jobs/'
for spec in sys.argv[2:]:
    jn, sids = spec.split(':')
    P = read_pieces(W + jn)
    for sid in [int(x) for x in sids.split(',')]:
        p = P[sid]
        b = open(os.path.join(W + jn, 'subm', str(sid)), 'rb').read()
        V, F = brep.parse(b)
        sh = brep.solid(V, F)
        g = GProp_GProps(); BRepGProp.SurfaceProperties_s(sh, g); area = g.Mass() / MM ** 2
        g2 = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g2); vol = abs(g2.Mass()) / MM ** 3
        used = sorted({i for f in F for i in f})
        print(jn, sid, p['name'], kind(p), 'L W T wt', round(p['L'], 3), round(p['W'], 3), round(p['T'], 4), round(p['wt'], 2),
              'nv nf', len(V), len(F), 'ext', np.round(np.ptp(V[used], 0), 3).tolist(),
              'area', round(area, 1), 'vol', round(vol, 1), 'vol_lb', round(vol * 0.2836, 1),
              'area*T*0.2836', round(area * p['T'] * 0.2836, 1), 'area/2*T*0.2836', round(area / 2 * p['T'] * 0.2836, 1),
              'bodies', len(brep.bodies(F)))
