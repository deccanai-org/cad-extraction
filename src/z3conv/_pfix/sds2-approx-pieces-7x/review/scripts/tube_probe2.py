import sys, os
import numpy as np
DEC, job = sys.argv[1], sys.argv[2]; sids = [int(x) for x in sys.argv[3].split(",")]
sys.path.insert(0, DEC)
import brep
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.gp import gp_Pnt
MM = 25.4
def vol(sh):
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); return abs(g.Mass()) / MM ** 3
for s in sids:
    V, F = brep.parse(open(os.path.join(job, "subm", str(s)), "rb").read())
    sh = brep.solid(V, F, repair=True)
    used = sorted({i for f in F for i in f}); U = V[used]; lo, hi = U.min(0), U.max(0)
    print(f"== {s} ext {np.ptp(U,0).round(3)} vol {vol(sh):.1f}")
    # slab-by-slab volume per unit x (= section area / cos) along local x, slabs 0.5 in thick at 9 stations
    for fx in np.linspace(0.02, 0.98, 9):
        x = lo[0] + fx * (hi[0] - lo[0]); dx = 0.5
        box = BRepPrimAPI_MakeBox(gp_Pnt((x - dx/2) * MM, (lo[1] - 1) * MM, (lo[2] - 1) * MM),
                                  gp_Pnt((x + dx/2) * MM, (hi[1] + 1) * MM, (hi[2] + 1) * MM)).Shape()
        c = BRepAlgoAPI_Common(sh, box).Shape()
        # y-range of the stored vertices near this x (where the tube sits) -> local slope
        near = U[np.abs(U[:, 0] - x) < 3]
        print(f"   x {x:9.2f}  slab vol/dx {vol(c)/dx:7.3f} in2   y-range of nearby vertices {near[:,1].min() if len(near) else 0:9.2f}..{near[:,1].max() if len(near) else 0:9.2f}")
    # vertex rings: print distinct x stations and the vertex count / y-span at each
    xs = np.round(U[:, 0], 2); st = np.unique(xs)
    print("   n stations", len(st), "first", st[:6], "last", st[-6:])
    for xv in list(st[:3]) + list(st[len(st)//2-1:len(st)//2+2]) + list(st[-3:]):
        q = U[xs == xv]; print(f"     x {xv:9.2f} n {len(q):3d} y {q[:,1].min():9.3f}..{q[:,1].max():9.3f} z {q[:,2].min():6.3f}..{q[:,2].max():6.3f}")
