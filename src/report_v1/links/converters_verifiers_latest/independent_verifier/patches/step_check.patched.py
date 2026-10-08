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
FAR_RE = re.compile(r"[(,]\s*-?\d{8,}")      # a CARTESIAN_POINT coordinate >= 1e7 mm (10 km) from the origin
CP_RE = re.compile(r"CARTESIAN_POINT\('[^']*',\(([^)]*)\)\)")
far_points = 0
far_first = None
with open(a.step, 'r', encoding='latin-1') as f:
    for line in f:
        for m in MARK:
            if m in line:
                mk[m] += line.count(m)
        if 'CARTESIAN_POINT' in line and FAR_RE.search(line):
            far_points += 1
            if far_first is None:
                for m_ in CP_RE.finditer(line):
                    if m_.group(1).count(',') == 2 and FAR_RE.search('(' + m_.group(1)):
                        far_first = [float(v_) for v_ in m_.group(1).split(',')]
                        break
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


# [z3v port 1 - ifc-step-verifier F_NOT_STEP / F_COMPRESSED / F_TRUNCATED / F_SCHEMA] file-level integrity, independent of OCC
# (OCC reads a cut-off file up to the cut without complaint: END-ISO-10303-21 is the only proof the file is complete)
with open(a.step, 'rb') as _fh:
    _head = _fh.read(65536); _fh.seek(max(0, out['bytes'] - 4096)); _tail = _fh.read()
out['iso_header'] = _head.lstrip(b'\xef\xbb\xbf \t\r\n').startswith(b'ISO-10303-21')
out['compressed'] = _head[:2] == b'\x1f\x8b' or _head[:4] == b'PK\x03\x04'
out['end_marker'] = b'END-ISO-10303-21' in _tail
_sc = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", _head)
out['schema_geometry'] = bool(_sc and re.search(rb'AP2(03|14|42)|CONFIG_CONTROL|AUTOMOTIVE_DESIGN|MANAGED_MODEL_BASED_3D_ENGINEERING', _sc.group(1), re.I))
del _head, _tail


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

# Far from the origin (geo-referenced models, 1.5e9 / 3.0e9 mm seen in SDS/2 exports) OpenCASCADE's 1e-7 mm tolerances
# are finer than the coordinates' own floating-point resolution (ulp(3e9 mm) = 4.8e-7 mm): the reader's shape healing
# throws and BRepCheck fails solids that read back valid 1 km from the origin. Such a file (no MAPPED_ITEM, whose local
# frames must not move) is read from a copy whose geometry points (3D CARTESIAN_POINTs other than the context origin
# (0,0,0)) are all shifted by the same whole number of km (exact decimal arithmetic: a rigid translation of the
# geometry, nothing else changes); bboxes are reported in the file's coordinates.
OFF = None
read_path = a.step


def _far_copy():
    """the whole-km translated copy described above -> (path, offset)"""
    from decimal import Decimal
    off = [int(math.floor(v_ / 1e6) * 1e6) for v_ in far_first]
    D_ = [Decimal(v_) for v_ in off]

    def _sh(m_):
        vals = m_.group(1).split(',')
        if len(vals) != 3:
            return m_.group(0)              # 2D (parameter-space / profile) points stay
        if all(float(v_) == 0.0 for v_ in vals):
            return m_.group(0)              # the origin of the representation context placement stays
        res_ = []
        for k_, v_ in enumerate(vals):
            x_ = format(Decimal(v_.strip()) - (D_[k_] if k_ < 3 else 0), 'f')
            res_.append(x_ if '.' in x_ else x_ + '.')
        return m_.group(0)[:m_.start(1) - m_.start(0)] + ','.join(res_) + '))'
    import tempfile
    tf_ = tempfile.NamedTemporaryFile(prefix='farcopy_', suffix='.step', delete=False, dir=os.path.dirname(os.path.abspath(a.out)) or None)
    with open(a.step, 'r', encoding='latin-1') as f, open(tf_.name, 'w', encoding='latin-1') as g:
        for line in f:
            g.write(CP_RE.sub(_sh, line) if 'CARTESIAN_POINT' in line else line)
    return tf_.name, off


# (verifier 10:10Z) the file is read in place first - consumers open it in place, and the translated read reported false
# invalids (11 on f451e1f2 where the in-place read has 0); the translated copy is read only when the in-place read fails
r = STEPControl_Reader()
st = r.ReadFile(a.step)
if far_points:
    out['far_points'] = far_points
    out['far_read'] = 'in_place'
if st != IFSelect_RetDone and far_points and far_first is not None and not mk['MAPPED_ITEM(']:
    read_path, OFF = _far_copy()
    r = STEPControl_Reader()
    st = r.ReadFile(read_path)
    out['translated_for_check_mm'] = OFF; out['far_read'] = 'translated (in-place read failed)'
    try:
        os.remove(read_path)
    except OSError:
        pass
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
impossible_names = []
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
                gbox.Add(b); rec['bbox'] = [round(v + (OFF[k % 3] if OFF else 0), 2) for k, v in enumerate(bb)]
            else:
                tot['nonfinite'] += 1; rec['nonfinite'] = True
    except Exception:
        pass
    if sols and (check_p >= 1.0 or rng.random() < check_p):
        vol = 0.0; val = 0
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
        # [z3v port 2 - ifc-step-verifier W_BROKEN_SOLID] a solid's volume can never exceed its own bounding box (x 1.001): a
        # self-overlapping solid (ifc2step hole loops wound like the outer loop) passes BRepCheck but has volume > box
        _bb = rec.get('bbox')
        if _bb and vol > 0:
            _bv = max(0.0, _bb[3] - _bb[0]) * max(0.0, _bb[4] - _bb[1]) * max(0.0, _bb[5] - _bb[2])
            if vol > _bv * 1.001 + 1e-6:
                tot['impossible'] = tot.get('impossible', 0) + 1; rec['impossible'] = True
                if len(impossible_names) < 50:
                    impossible_names.append([rec.get('pid'), rec.get('name'), round(vol, 1), round(_bv, 1)])
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
out['impossible_solids'] = tot.get('impossible', 0); out['impossible_examples'] = impossible_names
# [z3v port 3 - duplicates] a product written twice (same source id) and exactly coincident parts (same box centre + volume;
# db1-step-verifier W_DUPLICATES)
import collections as _col
_pn = _col.Counter(p.get('pid') for p in parts if p.get('pid') and (p.get('solids') or p.get('faces')))
out['duplicate_pid_parts'] = sum(n - 1 for n in _pn.values() if n > 1)
out['duplicate_pid_examples'] = [k for k, n in _pn.most_common(10) if n > 1]
_kn = _col.Counter()
for p in parts:
    _bb = p.get('bbox'); _v = p.get('volume')
    if _bb and _v:
        _kn[(round((_bb[0] + _bb[3]) / 2, 1), round((_bb[1] + _bb[4]) / 2, 1), round((_bb[2] + _bb[5]) / 2, 1), round(_v, -1))] += 1
out['coincident_duplicates'] = sum(n - 1 for n in _kn.values() if n > 1)
# [z3v port 4 - db1-step-verifier W_STRAY_PARTS / W_FAR_STRAY] parts cut off from the model (its _strays, unchanged): box centres
# linked within r = max(20 m, 10 x the 75th-percentile 3rd-neighbour spacing) via a grid of cell r + 26-neighbour union-find;
# a part is a stray when its cluster holds <= max(1, min(50, 1 %)) of the parts. Needs scipy (cKDTree); reported unavailable otherwise
try:
    import numpy as _np
    from scipy.spatial import cKDTree as _KD
    _pp = [p for p in parts if p.get('bbox')]
    _C = _np.array([[(p['bbox'][k] + p['bbox'][k + 3]) / 2 for k in range(3)] for p in _pp]) if _pp else _np.zeros((0, 3))
    _n = len(_C); _stray = _np.zeros(_n, bool)
    if _n >= 3:
        _k = min(4, _n); _kd, _ = _KD(_C).query(_C, k=_k)
        _r = max(20000.0, 10.0 * float(_np.percentile(_kd[:, _k - 1], 75)))
        _cell = _np.floor(_C / _r).astype(_np.int64)
        _keys, _inv = _np.unique(_cell, axis=0, return_inverse=True); _inv = _inv.ravel()
        _idx = {tuple(c): i for i, c in enumerate(_keys)}; _par = list(range(len(_keys)))
        def _find(x):
            while _par[x] != x:
                _par[x] = _par[_par[x]]; x = _par[x]
            return x
        for i, c in enumerate(_keys):
            for o in [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1) if (dx, dy, dz) > (0, 0, 0)]:
                j = _idx.get((c[0] + o[0], c[1] + o[1], c[2] + o[2]))
                if j is not None:
                    ra, rb = _find(i), _find(j)
                    if ra != rb: _par[ra] = rb
        _root = _np.array([_find(i) for i in range(len(_keys))])[_inv]
        _, _ri, _cnt = _np.unique(_root, return_inverse=True, return_counts=True)
        _stray = _cnt[_ri.ravel()] <= max(1, min(50, int(0.01 * _n)))
    out['stray_parts'] = int(_stray.sum())
    out['stray_examples'] = [[_pp[i].get('pid'), _pp[i].get('name'), [round(x, 1) for x in _C[i]]] for i in _np.flatnonzero(_stray)[:10]]
    if _n:
        _core = _C[~_stray] if (~_stray).any() else _C
        out['core_extent_mm'] = [round(float(x), 1) for x in _np.percentile(_core, 99, axis=0) - _np.percentile(_core, 1, axis=0)]
except ImportError:
    out['stray_check'] = 'unavailable (scipy not installed)'
except Exception as _e:
    out['stray_check'] = f'error {type(_e).__name__}: {str(_e)[:120]}'
out['roots_mapped_to_products'] = sum(1 for p in parts if p.get('pid') is not None or p.get('name') is not None)
if not gbox.IsVoid():
    out['bbox'] = [round(v + (OFF[k % 3] if OFF else 0), 3) for k, v in enumerate(gbox.Get())]
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
