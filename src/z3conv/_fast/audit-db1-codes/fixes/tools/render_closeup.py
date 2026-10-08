"""render_closeup.py STEP STEP_PARTS_JSONL_GZ OUT.png [--root N | --pick K] [--margin MM] [--axis X,Y,Z]:
close-up of one bolt group (IfcMechanicalFastener product) and every product whose bbox meets the window: plates/members translucent
blue, bolt solids orange; two views (iso + along the bolt axis); title lists the products drawn."""
import sys, json, gzip, math, argparse
import numpy as np
ap = argparse.ArgumentParser(); ap.add_argument('step'); ap.add_argument('parts'); ap.add_argument('out')
ap.add_argument('--root', type=int); ap.add_argument('--pick', type=int, default=0); ap.add_argument('--margin', type=float, default=120)
ap.add_argument('--axis'); ap.add_argument('--title', default='')
a = ap.parse_args()
P = [json.loads(l) for l in gzip.open(a.parts, 'rt')]
fast = [p for p in P if p.get('desc') == 'IfcMechanicalFastener' and p.get('bbox')]
tgt = next(p for p in P if p['i'] == a.root) if a.root else fast[min(a.pick, len(fast) - 1)]
bb = np.array(tgt['bbox'], float); lo = bb[:3] - a.margin; hi = bb[3:] + a.margin
sel = [p for p in P if p.get('bbox') and np.all(np.array(p['bbox'][3:]) >= lo) and np.all(np.array(p['bbox'][:3]) <= hi)]
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.BRep import BRep_Tool
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.TopoDS import topods
rd = STEPControl_Reader(); rd.ReadFile(a.step)
tris = []
for p in sel:
    rd.TransferRoot(p['i']); sh = rd.Shape(rd.NbShapes())
    BRepMesh_IncrementalMesh(sh, 0.3, False, 0.3, True)
    e = TopExp_Explorer(sh, TopAbs_FACE); kind = 'bolt' if p.get('desc') == 'IfcMechanicalFastener' else 'part'
    while e.More():
        f = topods.Face(e.Current()); loc = TopLoc_Location(); T = BRep_Tool.Triangulation(f, loc)
        if T is not None:
            tr = loc.Transformation()
            nodes = [T.Node(k).Transformed(tr) for k in range(1, T.NbNodes() + 1)]
            V = np.array([[n.X(), n.Y(), n.Z()] for n in nodes])
            for k in range(1, T.NbTriangles() + 1):
                i1, i2, i3 = T.Triangle(k).Get()
                tris.append((kind, V[[i1 - 1, i2 - 1, i3 - 1]]))
        e.Next()
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
ax_b = None
if a.axis:
    ax_b = np.array([float(x) for x in a.axis.split(',')])
fig = plt.figure(figsize=(13, 6.5))
L = np.array([0.4, 0.3, 0.85]); L /= np.linalg.norm(L)
if ax_b is None:
    fb = [p for p in sel if p['i'] == tgt['i']]
ax_dir = ax_b
views = [(25, -60), None]
for n, vw in enumerate(views):
    axp = fig.add_subplot(1, 2, n + 1, projection='3d')
    if vw is None:
        if ax_dir is not None:
            d = ax_dir / np.linalg.norm(ax_dir); el = math.degrees(math.asin(max(-1, min(1, d[2])))); az = math.degrees(math.atan2(d[1], d[0]))
        else:
            el, az = 0, 0
    else:
        el, az = vw
    for kind in ('part', 'bolt'):
        F = [t for k, t in tris if k == kind]
        if not F: continue
        F = np.array(F); nrm = np.cross(F[:, 1] - F[:, 0], F[:, 2] - F[:, 0]); nn = np.linalg.norm(nrm, axis=1); nn[nn == 0] = 1
        sh = np.abs((nrm / nn[:, None]) @ L) * 0.7 + 0.3
        base = np.array([0.25, 0.4, 0.75]) if kind == 'part' else np.array([0.95, 0.55, 0.1])
        col = np.clip(base[None, :] * sh[:, None], 0, 1)
        pc = Poly3DCollection(F, facecolors=np.c_[col, np.full(len(col), 0.35 if kind == 'part' else 1.0)], edgecolors='none')
        axp.add_collection3d(pc)
    c = (bb[:3] + bb[3:]) / 2; r = max(bb[3:] - bb[:3]) / 2 + a.margin * 0.6
    axp.set_xlim(c[0] - r, c[0] + r); axp.set_ylim(c[1] - r, c[1] + r); axp.set_zlim(c[2] - r, c[2] + r)
    axp.view_init(elev=el, azim=az); axp.set_box_aspect((1, 1, 1)); axp.set_axis_off()
    axp.set_title('iso' if n == 0 else f'along bolt axis (el {el:.0f}, az {az:.0f})', fontsize=9)
names = [f"{p['i']}:{(p.get('name') or '')[:38]}" for p in sel][:10]
fig.suptitle((a.title + '\n' if a.title else '') + f"target root {tgt['i']} {tgt.get('name', '')[:90]}\n" + '; '.join(names), fontsize=7)
plt.tight_layout(); plt.savefig(a.out, dpi=110)
print(json.dumps({'target': tgt['i'], 'drawn': len(sel), 'tris': len(tris)}))
