#!/usr/bin/env python3
"""render.py PIPE JOB OUT.png SPEC... : side-by-side v5.4 stand-in vs v5.5 build of single pieces.
SPEC = g:<sid> (grating) or r:<sid> (rod)."""
import sys, os, re
import numpy as np
PIPE, job, outp = sys.argv[1], sys.argv[2], sys.argv[3]
specs = sys.argv[4:]
sys.path.insert(0, os.path.join(PIPE, 'decode'))
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import to_step2 as T2, brep, grating
from piece_table import read_pieces
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopoDS import TopoDS
from OCP.BRep import BRep_Tool
from OCP.TopLoc import TopLoc_Location
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
MM = 25.4
def tris(shape, defl=0.2):
    BRepMesh_IncrementalMesh(shape, defl, False, 0.3, True)
    out = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face(ex.Current()); loc = TopLoc_Location()
        t = BRep_Tool.Triangulation_s(f, loc)
        if t is not None:
            tr = loc.Transformation()
            P = np.array([[t.Node(k).Transformed(tr).X(), t.Node(k).Transformed(tr).Y(), t.Node(k).Transformed(tr).Z()] for k in range(1, t.NbNodes() + 1)])
            for k in range(1, t.NbTriangles() + 1):
                a, b, c = t.Triangle(k).Get(); out.append(P[[a - 1, b - 1, c - 1]])
        ex.Next()
    return np.array(out) / MM
def wt(sh):
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); return abs(g.Mass()) / MM ** 3 * 0.2836
def draw(ax, T, title, color, lims=None):
    nrm = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]); nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
    lum = 0.35 + 0.65 * np.abs(nrm @ (np.array([0.4, -0.5, 0.77]) / 1.06))
    ax.add_collection3d(Poly3DCollection(T, facecolors=lum[:, None] * np.array(color), linewidths=0))
    lo, hi = (T.reshape(-1, 3).min(0), T.reshape(-1, 3).max(0)) if lims is None else lims
    c = (lo + hi) / 2; R = (hi - lo).max() / 2
    ax.set_xlim(c[0] - R, c[0] + R); ax.set_ylim(c[1] - R, c[1] + R); ax.set_zlim(c[2] - R, c[2] + R)
    ax.set_box_aspect((1, 1, 1)); ax.view_init(elev=35, azim=-60); ax.set_axis_off(); ax.set_title(title, fontsize=9)
    return lo, hi
pieces = read_pieces(job)
fig = plt.figure(figsize=(12, 5.2 * len(specs)), dpi=110)
for i, spec in enumerate(specs):
    kind, sid = spec.split(':'); sid = int(sid); p = pieces[sid]
    r = brep.parse(open(os.path.join(job, 'subm', str(sid)), 'rb').read())
    if kind == 'g':
        V = T2.piece_vertices(job, sid)
        loc = T2.plate_local(V, p)
        A = T2._local_prism(loc[0], loc[1])
        rec = T2._piece_record(job, sid, p['name'])
        B, info = grating.build(r[0], r[1], p['wt'], rec)
        ta = f"v5.4: {p['name']} as panel outline [approx]\n{wt(A):.1f} lb vs SDS2 {p['wt']:.1f} lb"
        tb = f"v5.5: bars + bands + {info.get('cross_bars', 0)} cross bars (exact)\n{wt(B):.1f} lb vs SDS2 {p['wt']:.1f} lb"
    else:
        V = T2.mesh_vertices(job, sid); a = int(np.argmax(np.ptp(V, 0)))
        A = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*(np.eye(3)[a] * V[:, a].min() * MM)), gp_Dir(*np.eye(3)[a])), p['W'] / 2 * MM, p['L'] * MM).Shape()
        segs = T2.turned_any_axis(r[0], r[1], p)
        q0, L, rr, u = segs[0]
        B = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*(q0 * MM)), gp_Dir(*u)), rr * MM, L * MM).Shape()
        ta = f"v5.4: {p['name']} straight-rod guess along local axis {'xyz'[a]} [approx]"
        tb = f"v5.5: exact cylinder on the end-cap axis, d={2*rr:.4g} in, L={L:.4g} in"
    Ta, Tb = tris(A), tris(B)
    allp = np.vstack([Ta.reshape(-1, 3), Tb.reshape(-1, 3), r[0][sorted({k for f in r[1] for k in f})]])
    lims = (allp.min(0), allp.max(0))
    draw(fig.add_subplot(len(specs), 2, 2 * i + 1, projection='3d'), Ta, ta, (0.8, 0.45, 0.35), lims)
    draw(fig.add_subplot(len(specs), 2, 2 * i + 2, projection='3d'), Tb, tb, (0.36, 0.52, 0.77), lims)
plt.tight_layout(); plt.savefig(outp); print('saved', outp)
