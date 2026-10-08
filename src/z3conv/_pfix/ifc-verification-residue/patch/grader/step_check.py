#!/usr/bin/env python3
"""Independent check of a STEP file as a CAD consumer sees it (pythonocc / OpenCASCADE).
usage: step_check.py FILE.step OUT.json [--png OUT.png] [--parts OUT.parts.jsonl.gz] [--max-check N] [--title T]

1. text pass: entity markers + PRODUCT chain (PRODUCT <- PDF <- PD <- PDS <- SDR) so every transferred root maps to its
   PRODUCT (id = source part id when the writer puts one there, name, description)
2. OCC read: each root transferred on its own -> per root: solids, BRepCheck validity per solid, volume, finite coords, bbox
   (more than N solids: a random sample of N is checked and the counts are extrapolated, flagged `sampled`)
3. render: triangulate (BRepMesh), isometric view, painter's algorithm, flat shading -> PNG; ink fraction of the image
   (`render_ink`, share of non-background pixels; < 0.002 = blank render)
Prints one JSON line (also written to OUT.json)."""
import sys, os, re, json, time, math, random, gzip, argparse

ap = argparse.ArgumentParser()
ap.add_argument('step'); ap.add_argument('out')
ap.add_argument('--png'); ap.add_argument('--parts'); ap.add_argument('--max-check', type=int, default=150000)
ap.add_argument('--title', default=''); ap.add_argument('--max-tris', type=int, default=1500000)
ap.add_argument('--no-occ', action='store_true')
ap.add_argument('--render-max-shapes', type=int, default=20000)
a = ap.parse_args()
T0 = time.time()
out = {'file': os.path.basename(a.step), 'bytes': os.path.getsize(a.step)}

# ------------------------------------------------------------------ 1. text pass
MARK = ['FACETED_BREP(', 'POLY_LOOP', 'CLOSED_SHELL(', 'OPEN_SHELL(', 'MANIFOLD_SOLID_BREP(', 'ADVANCED_FACE', 'SHELL_BASED_SURFACE_MODEL(',
        'TESSELLATED', 'TRIANGULATED_FACE_SET', 'NEXT_ASSEMBLY_USAGE_OCCURRENCE(', 'MAPPED_ITEM(']
mk = dict.fromkeys(MARK, 0)
ent_re = re.compile(r"^#(\d+)\s*=\s*([A-Z_0-9]+)\s*\((.*)\)\s*;\s*$", re.S)
prod, pdf, pd, pds, sdr = {}, {}, {}, {}, {}
schema = None


def refs(s):
    return [int(x) for x in re.findall(r'#(\d+)', s)]


def strs(s):
    return re.findall(r"'((?:[^']|'')*)'", s)


buf = ''
FAR_MM = 1e7                                   # 10 km
FAR_RE = re.compile(r"[(,]\s*-?\d{8,}")      # a coordinate >= 1e7 mm on a CARTESIAN_POINT line
CP_RE = re.compile(r"CARTESIAN_POINT\('[^']*',\(([^)]*)\)\)")
far_points = 0
far_first = None
with open(a.step, 'r', encoding='latin-1') as f:
    for line in f:
        for m in MARK:
            if m in line:
                mk[m] += line.count(m)
        if 'CARTESIAN_POINT' in line and FAR_RE.search(line):
            for m_ in CP_RE.finditer(line):
                v_ = m_.group(1).split(',')
                if len(v_) == 3 and max(abs(float(x_)) for x_ in v_) >= FAR_MM:
                    far_points += 1
                    if far_first is None:
                        far_first = [float(x_) for x_ in v_]
        if schema is None and 'FILE_SCHEMA' in line:
            schema = line.strip()[:200]
        if not ('PRODUCT' in line or 'SHAPE_DEFINITION_REPRESENTATION' in line or buf):
            continue
        buf += line
        if not buf.rstrip().endswith(';'):
            if len(buf) > 1 << 20:
                buf = ''
            continue
        st, buf = buf, ''
        m = ent_re.match(st.strip())
        if not m:
            continue
        eid, typ, body = int(m.group(1)), m.group(2), m.group(3)
        if typ == 'PRODUCT':
            s = strs(body); prod[eid] = (s[0] if s else '', s[1] if len(s) > 1 else '', s[2] if len(s) > 2 else '')
        elif typ in ('PRODUCT_DEFINITION_FORMATION', 'PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE'):
            r = refs(body); pdf[eid] = r[-1] if r else None
        elif typ in ('PRODUCT_DEFINITION', 'PRODUCT_DEFINITION_WITH_ASSOCIATED_DOCUMENTS'):
            r = refs(body); pd[eid] = r[0] if r else None
        elif typ == 'PRODUCT_DEFINITION_SHAPE':
            r = refs(body); pds[eid] = r[0] if r else None
        elif typ == 'SHAPE_DEFINITION_REPRESENTATION':
            r = refs(body); sdr[eid] = r[0] if r else None
out['markers'] = {k.rstrip('('): v for k, v in mk.items()}
out['schema'] = schema
out['products'] = len(prod)
out['approx_products'] = sum(1 for v in prod.values() if '[approx:' in (v[1] or '') or '[approx:' in (v[0] or ''))
_v6 = {}
for v in prod.values():
    d_ = v[2] or ''
    i_ = d_.find('[v6:')
    if i_ >= 0:
        for t_ in d_[i_ + 4:d_.find(']', i_)].split(','):
            t_ = t_.strip()
            if t_:
                _v6[t_] = _v6.get(t_, 0) + 1
if _v6:
    out['v6_tags'] = _v6
out['text_sec'] = round(time.time() - T0, 1)


def product_of(eid):
    """root entity id (SDR or PD) -> (id, name, description)"""
    try:
        if eid in sdr:
            eid = pds.get(sdr[eid])
        if eid in pd:
            return prod.get(pdf.get(pd[eid]))
    except Exception:
        pass
    return None


if a.no_occ:
    print(json.dumps(out)); json.dump(out, open(a.out, 'w')); sys.exit(0)

# ------------------------------------------------------------------ 2. OCC read
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL
from OCC.Core.BRepCheck import BRepCheck_Analyzer
from OCC.Core.GProp import GProp_GProps
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.TopoDS import TopoDS_Compound
from OCC.Core.BRep import BRep_Builder, BRep_Tool
try:
    from OCC.Core.BRepGProp import brepgprop
    vol_props = brepgprop.VolumeProperties
except ImportError:
    from OCC.Core.BRepGProp import brepgprop_VolumeProperties as vol_props
try:
    from OCC.Core.BRepBndLib import brepbndlib
    bnd_add = brepbndlib.Add
except ImportError:
    from OCC.Core.BRepBndLib import brepbndlib_Add as bnd_add

# Far from the origin (geo-referenced models: 1.5e9 / 3.0e9 mm in SDS/2 exports) OpenCASCADE's 1e-7 mm tolerances are
# finer than the coordinates' own floating-point resolution (ulp(3e9 mm) = 4.8e-7 mm): the reader's healing throws
# ('gp_Dir() - input vector has zero norm') and BRepCheck fails solids that read back valid 1 km from the origin. For
# such a file the solid checks (BRepCheck, volume) are taken from a second read of a copy in which every far point
# (a coordinate >= 10 km; local frames of shared representations and the context origin stay) is moved by the same
# whole number of km - exact decimal arithmetic, a rigid translation of the far geometry. Roots, products, faces and
# bboxes still come from the file itself.
r2 = None
if far_points and far_first is not None:
    from decimal import Decimal
    import tempfile
    OFF = [int(math.floor(v_ / 1e6) * 1e6) for v_ in far_first]
    D_ = [Decimal(v_) for v_ in OFF]

    def _sh(m_):
        vals = m_.group(1).split(',')
        if len(vals) != 3 or max(abs(float(v_)) for v_ in vals) < FAR_MM:
            return m_.group(0)
        res_ = []
        for k_, v_ in enumerate(vals):
            x_ = format(Decimal(v_.strip()) - D_[k_], 'f')
            res_.append(x_ if '.' in x_ else x_ + '.')
        return m_.group(0)[:m_.start(1) - m_.start(0)] + ','.join(res_) + '))'
    tf_ = tempfile.NamedTemporaryFile(prefix='farcopy_', suffix='.step', delete=False, dir=os.path.dirname(os.path.abspath(a.out)) or None)
    with open(a.step, 'r', encoding='latin-1') as f, open(tf_.name, 'w', encoding='latin-1') as g:
        for line in f:
            g.write(CP_RE.sub(_sh, line) if 'CARTESIAN_POINT' in line else line)
    r2 = STEPControl_Reader()
    if r2.ReadFile(tf_.name) != IFSelect_RetDone:
        r2 = None
    try:
        os.remove(tf_.name)
    except OSError:
        pass
    out['far_check'] = {'offset_mm': OFF, 'far_points': far_points, 'translated_read': r2 is not None, 'roots_checked_translated': 0}
r = STEPControl_Reader()
st = r.ReadFile(a.step)
out['read_status'] = 'ok' if st == IFSelect_RetDone else f'fail:{st}'
if st != IFSelect_RetDone:
    out['sec'] = round(time.time() - T0, 1)
    print(json.dumps(out)); json.dump(out, open(a.out, 'w')); sys.exit(0)
nroots = r.NbRootsForTransfer()
out['roots'] = nroots
model = r.WS().Model()
rng = random.Random(7)
# solids are checked (validity + volume) up to max_check: sample roots if needed
n_est_solids = mk['FACETED_BREP('] + mk['MANIFOLD_SOLID_BREP('] or nroots
check_p = 1.0 if n_est_solids <= a.max_check else a.max_check / float(n_est_solids)
out['check_fraction'] = round(check_p, 4)
builder = BRep_Builder(); comp = TopoDS_Compound(); builder.MakeCompound(comp)
gbox = Bnd_Box()
tot = dict(transferred=0, empty_roots=0, solids=0, shells=0, faces=0, checked=0, valid=0, invalid=0, nonpos_vol=0, nonfinite=0)
parts = []
invalid_names = []
rshapes = []
t_occ = time.time()
for i in range(1, nroots + 1):
    try:
        ent = r.RootForTransfer(i)
        try:
            lab = model.StringLabel(ent).ToCString()
            eid = int(lab.lstrip('#'))
        except Exception:
            eid = None
        p = product_of(eid) if eid else None
        ok = r.TransferRoot(i)
        if not ok:
            tot['empty_roots'] += 1; parts.append({'i': i, 'pid': p[0] if p else None, 'name': p[1] if p else None, 'solids': 0, 'empty': True}); continue
        sh = r.Shape(r.NbShapes())
    except Exception as e:
        tot['empty_roots'] += 1; continue
    if sh is None or sh.IsNull():
        tot['empty_roots'] += 1; parts.append({'i': i, 'pid': p[0] if p else None, 'name': p[1] if p else None, 'solids': 0, 'empty': True}); continue
    tot['transferred'] += 1
    builder.Add(comp, sh)
    if a.png:
        try:
            bx = Bnd_Box(); bnd_add(sh, bx, False)
            if not bx.IsVoid():
                q = bx.Get(); rshapes.append((math.dist(q[:3], q[3:]), sh))
        except Exception:
            pass
    rec = {'i': i, 'pid': p[0] if p else None, 'name': p[1] if p else None, 'desc': p[2] if p else None}
    ex = TopExp_Explorer(sh, TopAbs_SOLID); sols = []
    while ex.More():
        sols.append(ex.Current()); ex.Next()
    rec['solids'] = len(sols); tot['solids'] += len(sols)
    if not sols:
        exs = TopExp_Explorer(sh, TopAbs_SHELL); ns = 0
        while exs.More():
            ns += 1; exs.Next()
        rec['shells'] = ns; tot['shells'] += ns
    exf = TopExp_Explorer(sh, TopAbs_FACE); nf = 0
    while exf.More():
        nf += 1; exf.Next()
    rec['faces'] = nf; tot['faces'] += nf
    b = Bnd_Box()
    try:
        bnd_add(sh, b, False)
        if not b.IsVoid():
            bb = b.Get()
            if all(math.isfinite(v) and abs(v) < 1e10 for v in bb):
                gbox.Add(b); rec['bbox'] = [round(v, 2) for v in bb]
            else:
                tot['nonfinite'] += 1; rec['nonfinite'] = True
    except Exception:
        pass
    if sols and (check_p >= 1.0 or rng.random() < check_p):
        vol = 0.0; val = 0
        if r2 is not None:
            # same root of the translated copy (same structure, same root order): its solids carry the checks
            try:
                if r2.TransferRoot(i):
                    sh2 = r2.Shape(r2.NbShapes())
                    ex2 = TopExp_Explorer(sh2, TopAbs_SOLID); sols2 = []
                    while ex2.More():
                        sols2.append(ex2.Current()); ex2.Next()
                    if len(sols2) == len(sols):
                        sols = sols2; out['far_check']['roots_checked_translated'] += 1
            except Exception:
                pass
        for s in sols:
            try:
                v_ = BRepCheck_Analyzer(s).IsValid()
            except Exception:
                v_ = False
            val += bool(v_)
            g = GProp_GProps()
            try:
                vol_props(s, g); vv = g.Mass()
            except Exception:
                vv = float('nan')
            vol += vv
            if not (vv > 0):
                tot['nonpos_vol'] += 1
        tot['checked'] += len(sols); tot['valid'] += val; tot['invalid'] += len(sols) - val
        rec['valid'] = val; rec['volume'] = round(vol, 3)
        if val < len(sols) and len(invalid_names) < 50:
            invalid_names.append([rec.get('pid'), rec.get('name')])
    parts.append(rec)
out.update(tot)
out['occ_sec'] = round(time.time() - t_occ, 1)
if tot['checked']:
    f_ = tot['solids'] / tot['checked']
    out['valid_solids_est'] = int(round(tot['valid'] * f_)); out['invalid_solids_est'] = int(round(tot['invalid'] * f_))
    out['invalid_frac'] = round(tot['invalid'] / tot['checked'], 6)
out['sampled'] = check_p < 1.0
out['invalid_examples'] = invalid_names
out['roots_mapped_to_products'] = sum(1 for p in parts if p.get('pid') is not None or p.get('name') is not None)
if not gbox.IsVoid():
    out['bbox'] = [round(v, 3) for v in gbox.Get()]
if a.parts:
    with gzip.open(a.parts, 'wt') as g:
        for p in parts:
            g.write(json.dumps(p) + '\n')

# ------------------------------------------------------------------ 3. render
if a.png and tot['transferred']:
    t_r = time.time()
    try:
        import numpy as np
        from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
        from OCC.Core.TopLoc import TopLoc_Location
        from OCC.Core.TopoDS import topods
        bb = out.get('bbox')
        diag = math.dist(bb[:3], bb[3:]) if bb else 1000.0
        rcomp = comp
        if len(rshapes) > a.render_max_shapes:
            # bounded memory: draw the largest parts only (the caption says how many)
            rshapes.sort(key=lambda x: -x[0])
            rcomp = TopoDS_Compound(); builder.MakeCompound(rcomp)
            for _, sh_ in rshapes[:a.render_max_shapes]:
                builder.Add(rcomp, sh_)
            out['render_shapes'] = a.render_max_shapes
        BRepMesh_IncrementalMesh(rcomp, max(diag / 2000.0, 0.5), False, 0.5, False)   # single-threaded: many checks run per box
        tris = []; ntri = 0
        ex = TopExp_Explorer(rcomp, TopAbs_FACE)
        while ex.More():
            fc = topods.Face(ex.Current()); loc = TopLoc_Location()
            t = BRep_Tool.Triangulation(fc, loc)
            if t is not None:
                tr = loc.Transformation()
                nn = t.NbNodes()
                P = np.empty((nn, 3))
                for k in range(1, nn + 1):
                    q = t.Node(k).Transformed(tr); P[k - 1] = (q.X(), q.Y(), q.Z())
                for k in range(1, t.NbTriangles() + 1):
                    i1, i2, i3 = t.Triangle(k).Get()
                    tris.append((P[i1 - 1], P[i2 - 1], P[i3 - 1]))
                ntri += t.NbTriangles()
                if ntri > a.max_tris * 3:
                    break
            ex.Next()
        out['render_tris_total'] = ntri
        T = np.array(tris)
        if len(T) > a.max_tris:
            area = np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)
            T = T[np.argsort(-area)[:a.max_tris]]
        # isometric view (azimuth -45 deg, elevation 30 deg), z up
        az, el = math.radians(-45), math.radians(30)
        Rz = np.array([[math.cos(az), -math.sin(az), 0], [math.sin(az), math.cos(az), 0], [0, 0, 1]])
        Rx = np.array([[1, 0, 0], [0, math.cos(el - math.pi / 2), -math.sin(el - math.pi / 2)], [0, math.sin(el - math.pi / 2), math.cos(el - math.pi / 2)]])
        M = Rx @ Rz
        V = T.reshape(-1, 3) @ M.T
        V = V.reshape(-1, 3, 3)
        nrm = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        nrm /= (np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12)
        L = np.array([0.35, -0.55, 0.76]); L /= np.linalg.norm(L)
        lum = 0.30 + 0.70 * np.abs(nrm @ L)
        order = np.argsort(V[:, :, 2].mean(1))            # far first (painter)
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.collections import PolyCollection
        fig = plt.figure(figsize=(8, 6), dpi=100)
        ax = fig.add_axes([0, 0, 1, 0.94])
        col = lum[order, None] * np.array([0.33, 0.50, 0.78])
        pc = PolyCollection(V[order][:, :, :2], facecolors=col, edgecolors=col, linewidths=0.15, antialiased=False)
        ax.add_collection(pc)
        lo = V.reshape(-1, 3).min(0); hi = V.reshape(-1, 3).max(0)
        pad = 0.03 * max(hi[0] - lo[0], hi[1] - lo[1], 1e-6)
        ax.set_xlim(lo[0] - pad, hi[0] + pad); ax.set_ylim(lo[1] - pad, hi[1] + pad); ax.set_aspect('equal'); ax.axis('off')
        fig.text(0.01, 0.965, (a.title or os.path.basename(a.step))[:110], fontsize=8)
        fig.text(0.01, 0.94, f"{tot['transferred']} parts, {tot['solids']} solids, {len(T)} tris drawn", fontsize=7, color='#555')
        fig.canvas.draw()
        img = np.asarray(fig.canvas.buffer_rgba())[:, :, :3]
        h = img.shape[0]
        body = img[int(h * 0.07):]                        # exclude the caption band
        ink = float(((body < 245).any(axis=2)).mean())
        fig.savefig(a.png)
        plt.close(fig)
        out['render_ink'] = round(ink, 4); out['render_blank'] = ink < 0.002; out['render_sec'] = round(time.time() - t_r, 1)
    except Exception as e:
        out['render_error'] = f'{type(e).__name__}: {str(e)[:200]}'
out['sec'] = round(time.time() - T0, 1)
print(json.dumps(out))
json.dump(out, open(a.out, 'w'))
