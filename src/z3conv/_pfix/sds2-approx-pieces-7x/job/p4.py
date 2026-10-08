import sys, os, json, collections
import numpy as np
DEC = sys.argv[1]; jobs = sys.argv[2:]
sys.path.insert(0, DEC)
import brep
from piece_table import read_pieces, kind
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
MM = 25.4
for job in jobs:
    try:
        pieces = read_pieces(job)
    except Exception as e:
        print(os.path.basename(job), "ERR", e); continue
    neg = [s for s, p in pieces.items() if p["wt"] < 0]
    zero = [s for s, p in pieces.items() if p["wt"] == 0]
    H = collections.Counter(); ex = []
    for s in neg[:300]:
        fp = os.path.join(job, "subm", str(s))
        if not os.path.exists(fp): H["nofile"] += 1; continue
        r = brep.parse(open(fp, "rb").read())
        if r is None: H["noparse"] += 1; continue
        sh = brep.solid(*r, repair=True)
        if sh is None: H["nosolid"] += 1; continue
        g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g)
        rr = abs(g.Mass()) / MM ** 3 * 0.2836 / abs(pieces[s]["wt"])
        H["%.2f" % rr if 0.9 < rr < 1.1 else ("<0.9" if rr <= 0.9 else ">1.1")] += 1
        if len(ex) < 6: ex.append((s, pieces[s]["name"], round(pieces[s]["wt"], 3), round(rr, 4), round(pieces[s]["L"], 2)))
    print(os.path.basename(job)[:30], "pieces", len(pieces), "neg", len(neg), "zero", len(zero), dict(H), ex)
