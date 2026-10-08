import os, sys
import numpy as np
from instances import material_instances, subm_vertices
from piece_table import read_pieces, kind
job = sys.argv[1]
pieces = read_pieces(job)
shown = 0
for n in range(1, 9091):
    if not os.path.exists(os.path.join(job, "mem", str(n))): continue
    for sid, M, o in material_instances(job, n, pieces)[1]:
        p = pieces[sid]; V = subm_vertices(job, sid)
        if V is None: continue
        print(n, sid, kind(p), p["name"], "L W T", round(p["L"], 3), round(p["W"], 3), round(p["T"], 3), "vbbox", np.round(V.min(0), 3), np.round(V.max(0), 3))
        shown += 1
    if shown > 12: break
