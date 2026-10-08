"""Read-back check timing: sequential vs BRepCheck parallel flag vs thread pool (does OCP release the GIL?).
usage: vthr.py <pipeline decode dir> <file.step> [threads]"""
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
from concurrent.futures import ThreadPoolExecutor

path = sys.argv[2]; nt = int(sys.argv[3]) if len(sys.argv) > 3 else 4
t = time.time(); items = VS.load(path); t_load = time.time() - t
shapes = [s for _, s in items]
print("leaves", len(shapes), "load_s", round(t_load, 1), flush=True)


def one(sh, par=False):
    ex = TopExp_Explorer(sh, TopAbs_SOLID); ns = 0
    while ex.More(): ns += 1; ex.Next()
    v = BRepCheck_Analyzer(sh, True, par).IsValid()
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g)
    b = Bnd_Box(); BRepBndLib.Add_s(sh, b); lo, hi = b.CornerMin(), b.CornerMax()
    return (ns > 0, v, round(g.Mass(), 3), round(lo.X(), 3), round(hi.Z(), 3))


res = {}
t = time.time(); res["seq"] = [one(s) for s in shapes]; tseq = time.time() - t
print("sequential_s", round(tseq, 1), flush=True)
t = time.time(); res["par_flag"] = [one(s, True) for s in shapes]; tpar = time.time() - t
print("brepcheck_parallel_flag_s", round(tpar, 1), flush=True)
t = time.time()
with ThreadPoolExecutor(nt) as ex:
    res["threads"] = list(ex.map(one, shapes, chunksize=64) if False else ex.map(one, shapes))
tthr = time.time() - t
print(f"threads{nt}_s", round(tthr, 1), flush=True)
same = res["seq"] == res["par_flag"] == res["threads"]
print(json.dumps(dict(leaves=len(shapes), load_s=round(t_load, 1), sequential_s=round(tseq, 1),
                      parallel_flag_s=round(tpar, 1), threads_s=round(tthr, 1), threads=nt, identical=same,
                      invalid=sum(not r[1] for r in res["seq"]))))
