import sys, os
import numpy as np
DEC = sys.argv[1]; job = sys.argv[2]; sids = [int(x) for x in sys.argv[3].split(",")]
sys.path.insert(0, DEC)
import brep
from piece_table import read_pieces
from sds2job import read_shapes
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
MM = 25.4
P = read_pieces(job); S = read_shapes(job)
for s in sids:
    p = P[s]; r = brep.parse(open(os.path.join(job, "subm", str(s)), "rb").read())
    sh = brep.solid(*r, repair=True)
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); vol = abs(g.Mass()) / MM ** 3
    g2 = GProp_GProps(); BRepGProp.SurfaceProperties_s(sh, g2); area = g2.Mass() / MM ** 2
    sec = S.get(p["sec"])
    used = sorted({i for f in r[1] for i in f}); ext = np.ptp(r[0][used], 0)
    print(s, p["name"], "L", round(p["L"], 2), "W", p["W"], "T", p["T"], "wt", round(p["wt"], 2), "vol", round(vol, 2), "wt_brep", round(vol * 0.2836, 1),
          "area", round(area, 1), "2V/A", round(2 * vol / area, 4), "ext", ext.round(3), "sec", sec and (sec.d, sec.bf, sec.tw, sec.weight))
