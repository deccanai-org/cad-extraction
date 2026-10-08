import sys, os
sys.path.insert(0, sys.argv[1])
import numpy as np
import brep
from piece_table import read_pieces
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.BRepCheck import BRepCheck_Analyzer
import time
MM = 25.4
W = '/work/agentwork/sds2-pieces-not-built/jobs/'
for spec in sys.argv[2:]:
    jn, sids = spec.split(':')
    P = read_pieces(W + jn)
    for sid in [int(x) for x in sids.split(',')]:
        p = P[sid]; t0 = time.time()
        V, F = brep.parse(open(os.path.join(W + jn, 'subm', str(sid)), 'rb').read())
        sh = brep.solid(V, F)
        if sh is None:
            print(jn, sid, p['name'], 'no solid'); continue
        g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); vol = abs(g.Mass()) / MM ** 3
        print(jn, sid, p['name'], 'type', sh.ShapeType(), 'valid', BRepCheck_Analyzer(sh).IsValid(), 'vol_lb', round(vol * 0.2836, 2), 'sds2', round(p['wt'], 2),
              'ratio', round(vol * 0.2836 / p['wt'], 4) if p['wt'] > 0 else None, 'bodies', len(brep.bodies(F)), 't', round(time.time() - t0, 2))
