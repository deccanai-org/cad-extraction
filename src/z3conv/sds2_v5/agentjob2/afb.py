"""Diagnose approximate pieces: why the stored B-rep is not used. usage: afb.py <decode dir> <job dir> <pieces.csv>"""
import sys, csv, collections, json
import numpy as np
sys.path.insert(0, sys.argv[1])
import brep
from piece_table import read_pieces
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
job, pc = sys.argv[2], sys.argv[3]
P = read_pieces(job)
rows = list(csv.DictReader(open(pc)))
fb = sorted({int(x['piece']) for x in rows if x['builder'] in ('bent_plate_fallback', 'plate_fallback', 'profile_fallback', 'plate_hull_fallback', 'vertex_box_fallback')})
out = []
for sid in fb:
    p = P[sid]
    try:
        b = open(f"{job}/subm/{sid}", "rb").read()
    except OSError:
        out.append(dict(sid=sid, name=p['name'], why='no file')); continue
    r = brep.parse(b)
    if r is None:
        out.append(dict(sid=sid, name=p['name'], why='parse None', size=len(b))); continue
    V, F = r
    E = collections.Counter()
    for f in F:
        for l in brep.loops_of(f):
            for a, c in zip(l, l[1:] + l[:1]):
                E[(min(a, c), max(a, c))] += 1
    sh = brep.solid(V, F); ratio = None
    if sh is not None:
        g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g)
        ratio = abs(g.Mass()) / 25.4 ** 3 * 0.2836 / p['wt'] if p['wt'] > 0 else None
    used = sorted({i for f in F for i in f})
    out.append(dict(sid=sid, name=p['name'], nf=len(F), bodies=len(brep.bodies(F)), edge_use=dict(collections.Counter(E.values())),
                    solid=sh is not None, ratio=None if ratio is None else round(ratio, 3), wt=round(p['wt'], 2),
                    ext=np.round(np.ptp(V[used], 0), 2).tolist(), L=round(p['L'], 2)))
for o in out:
    print(json.dumps(o))
