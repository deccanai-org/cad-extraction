import sys, os, numpy as np, ifcopenshell, ifcopenshell.geom
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
f = ifcopenshell.open(sys.argv[1]); out = sys.argv[2]
flt = sys.argv[3] if len(sys.argv) > 3 else None
s = ifcopenshell.geom.settings(); s.set('use-world-coords', True)
it = ifcopenshell.geom.iterator(s, f, 4); tris = []; cols = []
cmap = {'IfcPipeSegment': (0.6,0.65,0.7), 'IfcPipeFitting': (0.3,0.45,0.8), 'IfcValve': (0.85,0.1,0.1), 'IfcFlowInstrument': (1,0.6,0), 'IfcDiscreteAccessory': (0.3,0.3,0.3),
        'IfcBeam': (0.9,0.5,0.1), 'IfcColumn': (0.6,0.3,0.1), 'IfcMember': (0.95,0.8,0.2)}
if it.initialize():
    while True:
        sh = it.get(); e = f.by_guid(sh.guid)
        v = np.array(sh.geometry.verts).reshape(-1, 3); fc = np.array(sh.geometry.faces).reshape(-1, 3)
        tags=os.environ.get('TAGS')
        if (flt is None or flt in (e.Name or '')) and (not tags or (e.Tag in tags.split(',')) or any(t in (e.Name or '') for t in [])):
            tris.append(v[fc]); cols += [cmap.get(e.is_a(), (0.5, 0.5, 0.9))] * len(fc)
        if not it.next(): break
T = np.concatenate(tris)
import os
crop = os.environ.get('CROP')
if crop:
    mc = f.by_type('IfcMapConversion')[0]; org = np.array([mc.Eastings, mc.Northings, mc.OrthogonalHeight])
    cx, cy, cz, rr = [float(x) for x in crop.split(',')]
    cen = np.array([cx, cy, cz]) - org
    keep = (np.abs(T.mean(1) - cen) < rr).all(1)
    T = T[keep]; cols = list(np.array(cols)[keep])
c = T.reshape(-1, 3); lo, hi = c.min(0), c.max(0)
fig = plt.figure(figsize=(14, 10)); ax = fig.add_subplot(111, projection='3d')
L = np.array([0.4, -0.5, 0.75]); L /= np.linalg.norm(L)
n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]); n /= (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)
sh = 0.35 + 0.65 * np.abs(n @ L)
fc = np.array(cols) * sh[:, None]
ax.add_collection3d(Poly3DCollection(T, facecolors=np.clip(fc, 0, 1), edgecolors='none'))
m = (lo + hi) / 2; r = (hi - lo).max() / 2
ax.set_xlim(m[0] - r, m[0] + r); ax.set_ylim(m[1] - r, m[1] + r); ax.set_zlim(m[2] - r, m[2] + r)
ax.view_init(elev=float(sys.argv[4]) if len(sys.argv) > 4 else 25, azim=float(sys.argv[5]) if len(sys.argv) > 5 else -60)
plt.tight_layout(); plt.savefig(out, dpi=90); print('tris', len(T), 'bbox', lo, hi)
