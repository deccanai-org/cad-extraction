"""a944_hit.py : do the 68 refused (self-intersecting arc outline) BL25 cut bodies of a944 touch their parent part at all?
Convex hull of the outline (+ the arc) x depth, OCC common with the parent solid from the patched decoder IFC."""
import sys, os, re, json, gzip, numpy as np
W = '/work/agentwork/cut-not-applied'; ID = 'a94442572f225f50'
sys.path.insert(0, W + '/kitp4')
import db1dec
data = db1dec.load(f'{W}/src/{ID}.db1'); eng = 7.64
L = json.load(open(W + '/kitp4/layouts.json')); lay = L['7.64']['layout']; var = [v['layout'] for v in L.values() if v.get('layout')]
db, pts, cs, lay = db1dec.decode(data, lay, var, True)
M = db1dec.members(db, pts, cs, lay); links = db.find_cut_links(M)
par = {c: p for p, cc in links.items() for c in cc}
bad = [m for m in M if m.get('cut') and m['prof'] == 'BL25' and db.polygon(lay, m) is None]
pl = {p[0]: p for p in json.load(gzip.open(f'{W}/pipes2/kitp2/{ID}/convert.json.parts.json.gz', 'rt'))}
import ifcopenshell, ifcopenshell.geom
from OCC.Core.gp import gp_Pnt, gp_Vec
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
def hull2(P):
    P = sorted(map(tuple, P))
    def cross(o, a, b): return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in P:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0: lo.pop()
        lo.append(p)
    for p in reversed(P):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0: up.pop()
        up.append(p)
    return np.array(lo[:-1] + up[:-1])
f = ifcopenshell.open(f'{W}/pipes2/kitp2/{ID}/model.ifc')
S = ifcopenshell.geom.settings(); S.set('use-world-coords', True); S.set('use-python-opencascade', True)
res = []
for m in bad:
    pts2 = np.array([p[:2] for p in db.outline_points(lay, m)])
    # add arc samples: circle through P0, P1, P2 (the arc point at index 1)
    C = db1dec._circ(pts2[0], pts2[1], pts2[2])
    extra = []
    if C is not None:
        r = np.linalg.norm(pts2[0] - C); a0, a2 = [np.arctan2(*(p - C)[::-1]) for p in (pts2[0], pts2[2])]
        for t in np.linspace(0, 1, 33):
            for a in (a0 + (a2 - a0) * t, a0 + (a2 - a0 + 2 * np.pi) * t, a0 + (a2 - a0 - 2 * np.pi) * t):
                extra.append(C + r * np.array([np.cos(a), np.sin(a)]))
    allp = np.vstack([pts2] + ([np.array(extra)] if extra else []))
    hull = hull2(allp)
    u = m['x'] / np.linalg.norm(m['x']); v = m['y'] - (m['y'] @ u) * u; v /= np.linalg.norm(v); n = np.cross(u, v)
    t = 25.0; base = m['O'] - n * t / 2
    poly = BRepBuilderAPI_MakePolygon()
    for q in hull:
        w = base + u * q[0] + v * q[1]; poly.Add(gp_Pnt(*(w / 1000.0)))
    poly.Close()
    prism = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(poly.Wire()).Face(), gp_Vec(*(n * t / 1000.0))).Shape()
    p = par.get(m['seq']); pe = pl.get(p)
    if not pe or not pe[5]: res.append((m['seq'], p, 'parent not written')); continue
    sh = ifcopenshell.geom.create_shape(S, f.by_guid(pe[5])).geometry
    com = BRepAlgoAPI_Common(sh, prism); com.Build(); g = GProp_GProps(); brepgprop.VolumeProperties(com.Shape(), g)
    gp2 = GProp_GProps(); brepgprop.VolumeProperties(prism, gp2)
    res.append((m['seq'], p, pe[1], round(g.Mass() * 1e9, 1), round(gp2.Mass() * 1e9, 1)))
import collections
print('refused cut bodies', len(bad), 'parents', collections.Counter(r[2] for r in res if len(r) > 3).most_common(4))
print('hull-prism volume (mm3) e.g.', res[0][4] if len(res[0]) > 4 else None)
print('intersection with the parent (mm3): zero', sum(1 for r in res if len(r) > 3 and r[3] <= 0.5), 'non-zero', sum(1 for r in res if len(r) > 3 and r[3] > 0.5), 'examples', [r for r in res if len(r) > 3][:5])
