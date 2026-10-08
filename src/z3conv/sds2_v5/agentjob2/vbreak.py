"""Read-back cost breakdown per check: BRepCheck / volume / bbox / solid count, and a per-part volume cache.
usage: vbreak.py <pipeline decode dir> <file.step>"""
import sys, time, json
sys.path.insert(0, sys.argv[1])
import verify_step as VS
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID
t = time.time(); items = VS.load(sys.argv[2]); tl = time.time() - t
S = [s for _, s in items]
out = dict(leaves=len(S), load_s=round(tl, 1))
t = time.time(); ns = []
for s in S:
    ex = TopExp_Explorer(s, TopAbs_SOLID); k = 0
    while ex.More(): k += 1; ex.Next()
    ns.append(k)
out["count_s"] = round(time.time() - t, 1)
t = time.time(); V = [BRepCheck_Analyzer(s).IsValid() for s in S]; out["brepcheck_s"] = round(time.time() - t, 1)
t = time.time(); vol = []
for s in S:
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(s, g); vol.append(g.Mass())
out["volume_s"] = round(time.time() - t, 1)
t = time.time(); cache = {}; vol2 = []
for s in S:
    k = s.TShape().__hash__() if hasattr(s.TShape(), "__hash__") else id(s.TShape())
    if k not in cache:
        g = GProp_GProps(); BRepGProp.VolumeProperties_s(s, g); cache[k] = g.Mass()
    vol2.append(cache[k])
out["volume_cached_s"] = round(time.time() - t, 1); out["unique_tshapes"] = len(cache)
out["volume_total_diff_rel"] = abs(sum(abs(v) for v in vol) - sum(abs(v) for v in vol2)) / max(sum(abs(v) for v in vol), 1e-9)
t = time.time()
for s in S:
    b = Bnd_Box(); BRepBndLib.Add_s(s, b)
out["bbox_s"] = round(time.time() - t, 1)
print(json.dumps(out))
