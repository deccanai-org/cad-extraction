"""Offscreen PNG renders of GLB files (pyrender + Mesa llvmpipe over EGL, no display).

render.py views OUT_PREFIX GLB [GLB ...] [--offsets json] [--size 1600x1200] [--views iso_ne,iso_sw,top,side]
GLBs are Y-up (IfcConvert); several GLBs of one area are merged with per-file offsets (local origins).
"""
import os, sys, json, math, argparse
os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')
os.environ.setdefault('EGL_PLATFORM', 'surfaceless')
_vend = os.path.join(os.path.dirname(os.path.dirname(sys.executable)), 'share', 'glvnd', 'egl_vendor.d', '50_mesa.json')
if os.path.exists(_vend):
    os.environ.setdefault('__EGL_VENDOR_LIBRARY_FILENAMES', _vend)
import numpy as np
import trimesh

_R = None


def renderer(w, h):
    global _R
    import pyrender
    if _R is None or _R.viewport_width != w or _R.viewport_height != h:
        if _R is not None:
            _R.delete()
        _R = pyrender.OffscreenRenderer(w, h)
    return _R


def load_scene(glbs, offsets=None):
    """-> list of (trimesh.Trimesh with vertex/face colours in world Y-up, name)"""
    meshes = []
    for k, g in enumerate(glbs):
        sc = trimesh.load(g, force='scene')
        off = np.zeros(3)
        if offsets is not None:
            o = np.asarray(offsets[k], float)          # IFC-frame offset (x, y, z) -> glTF (x, z, -y)
            off = np.array([o[0], o[2], -o[1]])
        for name, geom in sc.geometry.items():
            pass
        for node in sc.graph.nodes_geometry:
            T, gname = sc.graph[node]
            geom = sc.geometry[gname]
            if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
                continue
            m = geom.copy()
            m.apply_transform(T)
            if off.any():
                m.apply_translation(off)
            meshes.append(m)
    return meshes


def look_at(eye, target, up):
    f = target - eye; f /= np.linalg.norm(f)
    s = np.cross(f, up); s /= np.linalg.norm(s)
    u = np.cross(s, f)
    M = np.eye(4)
    M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = s, u, -f, eye
    return M


VIEWS = {'iso_ne': (1.0, 0.8, -1.0), 'iso_sw': (-1.0, 0.8, 1.0), 'iso_nw': (-1.0, 0.8, -1.0), 'top': (0.0, 1.0, 0.0001), 'side': (0.0, 0.25, 1.0)}


def render(meshes, out_prefix, views=('iso_ne',), size=(1600, 1200), bg=(0.93, 0.94, 0.96)):
    import pyrender
    if not meshes:
        return []
    sc = pyrender.Scene(bg_color=list(bg) + [1.0], ambient_light=[0.22, 0.22, 0.22])
    allv = []
    for m in meshes:
        try:
            pm = pyrender.Mesh.from_trimesh(m, smooth=False)
        except Exception:
            m2 = trimesh.Trimesh(m.vertices, m.faces, process=False)
            pm = pyrender.Mesh.from_trimesh(m2, smooth=False)
        sc.add(pm)
        allv.append(m.bounds)
    B = np.array(allv)
    lo, hi = B[:, 0].min(0), B[:, 1].max(0)
    full_lo, full_hi = lo.copy(), hi.copy()
    # frame perspective views on the densest cluster (areas can span hundreds of metres): weighted grid density
    cen = (B[:, 0] + B[:, 1]) / 2; wgt = np.linalg.norm(B[:, 1] - B[:, 0], axis=1) + 1e-3
    ext = hi - lo
    cell = float(os.environ.get('S3D_RENDER_CELL', '12'))
    if len(B) > 3 and max(ext[0], ext[2]) > 5 * cell:
        key = np.floor(cen[:, [0, 2]] / cell).astype(np.int64)
        from collections import defaultdict
        acc = defaultdict(float)
        for (i, j), wv in zip(map(tuple, key), wgt):
            acc[(i, j)] += wv
        best = max(acc, key=lambda k: sum(acc.get((k[0] + a, k[1] + b), 0.0) for a in (-1, 0, 1) for b in (-1, 0, 1)))
        sel = (np.abs(key[:, 0] - best[0]) <= 1) & (np.abs(key[:, 1] - best[1]) <= 1)
        if sel.sum() >= 1:
            lo, hi = B[sel, 0].min(0), B[sel, 1].max(0)
            wlo = np.array([(best[0] - 1) * cell, lo[1], (best[1] - 1) * cell]); whi = np.array([(best[0] + 2) * cell, hi[1], (best[1] + 2) * cell])
            lo, hi = np.maximum(lo, wlo), np.minimum(hi, whi)
    c = (lo + hi) / 2; rad = float(np.linalg.norm(hi - lo)) / 2 + 1e-3
    out = []
    R = renderer(*size)
    for v in views:
        d = np.array(VIEWS[v], float); d /= np.linalg.norm(d)
        if v == 'top':
            lo_, hi_ = full_lo, full_hi
            asp = size[0] / size[1]
            xm = max((hi_[0] - lo_[0]) / 2, (hi_[2] - lo_[2]) / 2 * asp) * 1.05 + 1e-3
            cam = pyrender.OrthographicCamera(xmag=xm, ymag=xm / asp, znear=0.01, zfar=float(np.linalg.norm(hi_ - lo_)) * 10 + 10)
            up = np.array([0, 0, -1.0])
        else:
            yfov = math.radians(35)
            cam = pyrender.PerspectiveCamera(yfov=yfov, aspectRatio=size[0] / size[1], znear=max(rad / 1000, 0.01), zfar=rad * 20)
            up = np.array([0, 1.0, 0])
        dist = rad / math.sin(math.radians(35) / 2) * 1.02
        eye = c + d * dist
        if v == 'top':
            fc = (full_lo + full_hi) / 2; frad = float(np.linalg.norm(full_hi - full_lo)) / 2 + 1
            eye = fc + d * frad * 3; c_ = fc
        else:
            c_ = c
        pose = look_at(eye, c_, up)
        cn = sc.add(cam, pose=pose)
        ln = sc.add(pyrender.DirectionalLight(color=[1.0, 1.0, 1.0], intensity=2.2), pose=pose)
        l2 = sc.add(pyrender.DirectionalLight(color=[1.0, 1.0, 1.0], intensity=0.9), pose=look_at(c + np.array([0.3, 1.0, 0.2]) * dist, c, np.array([0, 0, 1.0])))
        col, dep = R.render(sc)
        sc.remove_node(cn); sc.remove_node(ln); sc.remove_node(l2)
        from PIL import Image
        p = '%s__%s.png' % (out_prefix, v)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        Image.fromarray(col).save(p + '.tmp.png')
        os.replace(p + '.tmp.png', p)
        cover = float((dep > 0).mean())
        out.append({'png': p, 'view': v, 'coverage': round(cover, 4), 'bounds_yup': [float(x) for x in list(lo) + list(hi)]})
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('out_prefix'); ap.add_argument('glbs', nargs='+')
    ap.add_argument('--offsets'); ap.add_argument('--size', default='1600x1200'); ap.add_argument('--views', default='iso_ne')
    a = ap.parse_args()
    offs = json.loads(a.offsets) if a.offsets else None
    w, h = [int(x) for x in a.size.split('x')]
    print(json.dumps(render(load_scene(a.glbs, offs), a.out_prefix, a.views.split(','), (w, h))))
