"""render_pair.py SPEC.json OUT.png : before/after close-up of decoded parts, meshed by the IFC kernel (booleans applied as written).
SPEC: {"title": str, "panels": [{"label": str, "ifc": path, "parts": [[GlobalId, role]...]}...], "crop": [xmin,ymin,zmin,xmax,ymax,zmax] | null,
       "elev": deg, "azim": deg}   role: 'part' (steel) | 'phantom' (cut body written as steel) """
import sys, json, numpy as np
import ifcopenshell, ifcopenshell.geom
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
spec = json.load(open(sys.argv[1]))
S = ifcopenshell.geom.settings(); S.set('use-world-coords', True); S.set('use-python-opencascade', True)
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCC.Core.gp import gp_Pnt
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCC.Core.BRep import BRep_Tool
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.TopoDS import topods
def tris(shape, crop):
    """shape (metres) clipped to the crop box (mm) by an OCC boolean, meshed -> (n, 3, 3) triangles in mm"""
    if crop:
        c = [x / 1000.0 for x in crop]
        box = BRepPrimAPI_MakeBox(gp_Pnt(*c[:3]), gp_Pnt(*c[3:])).Shape()
        op = BRepAlgoAPI_Common(shape, box); op.Build(); shape = op.Shape()
    BRepMesh_IncrementalMesh(shape, 0.0005, False, 0.3, True)
    out = []; ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        fc = topods.Face(ex.Current()); loc = TopLoc_Location(); tr = BRep_Tool.Triangulation(fc, loc)
        if tr is not None:
            T = loc.Transformation(); P = [tr.Node(i).Transformed(T) for i in range(1, tr.NbNodes() + 1)]
            P = np.array([[p.X(), p.Y(), p.Z()] for p in P]) * 1000.0
            for i in range(1, tr.NbTriangles() + 1):
                a, b, c_ = tr.Triangle(i).Get()
                out.append(P[[a - 1, c_ - 1, b - 1]] if fc.Orientation() == TopAbs_REVERSED else P[[a - 1, b - 1, c_ - 1]])
        ex.Next()
    return np.array(out).reshape(-1, 3, 3)
COL = {'part': '#9aa3ad', 'phantom': '#eb6834'}
fig = plt.figure(figsize=(6.2 * len(spec['panels']), 6.4), facecolor='#fcfcfb')
lims = None
meshes = []
for p in spec['panels']:
    f = ifcopenshell.open(p['ifc']); M = []
    for gid, role in p['parts']:
        sh = ifcopenshell.geom.create_shape(S, f.by_guid(gid))
        M.append((tris(sh.geometry, spec.get('crop')), role))
    meshes.append(M)
allv = np.concatenate([T.reshape(-1, 3) for M in meshes for T, _ in M if len(T)])
if spec.get('auto_view', True):
    # look at the parent's broad face: camera along its thinnest principal direction, tilted 25 deg about the longest one
    pv = meshes[-1][0][0].reshape(-1, 3); pv = pv - pv.mean(0)
    w, V = np.linalg.eigh(pv.T @ pv); nrm, mid, lng = V[:, 0], V[:, 1], V[:, 2]
    d = np.cos(np.radians(25)) * nrm + np.sin(np.radians(25)) * mid
    if d[2] < 0: d = -d
    spec['elev'] = float(np.degrees(np.arcsin(np.clip(d[2], -1, 1)))); spec['azim'] = float(np.degrees(np.arctan2(d[1], d[0])))
lo, hi = allv.min(0), allv.max(0); ctr = (lo + hi) / 2; r = (hi - lo).max() / 2
light = np.array([0.4, -0.5, 0.75]); light /= np.linalg.norm(light)
for i, (p, M) in enumerate(zip(spec['panels'], meshes)):
    ax = fig.add_subplot(1, len(spec['panels']), i + 1, projection='3d'); ax.set_facecolor('#fcfcfb')
    for T, role in M:
        if not len(T): continue
        n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]); nn = np.linalg.norm(n, axis=1, keepdims=True); nn[nn == 0] = 1; n /= nn
        shade = 0.45 + 0.55 * np.abs(n @ light)
        base = np.array(matplotlib.colors.to_rgb(COL[role]))
        pc = Poly3DCollection(T, facecolors=np.clip(base[None, :] * shade[:, None], 0, 1), edgecolors='none', linewidths=0)
        ax.add_collection3d(pc)
    ax.set_xlim(ctr[0] - r, ctr[0] + r); ax.set_ylim(ctr[1] - r, ctr[1] + r); ax.set_zlim(ctr[2] - r, ctr[2] + r)
    ax.view_init(elev=spec.get('elev', 20), azim=spec.get('azim', -60)); ax.set_box_aspect((1, 1, 1)); ax.set_axis_off()
    ax.set_title(p['label'], fontsize=11, color='#0b0b0b', loc='left')
fig.suptitle(spec['title'], fontsize=12, color='#0b0b0b', x=0.02, ha='left')
fig.text(0.02, 0.02, 'grey: steel parts as written to STEP   orange: cut body written as a steel part (before)', fontsize=9, color='#52514e')
fig.savefig(sys.argv[2], dpi=110, facecolor='#fcfcfb'); print('wrote', sys.argv[2])
