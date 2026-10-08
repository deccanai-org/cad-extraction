"""cut-plane validation by the Tekla IFC solid of the same part (GUID join): after the plane is applied, every IFC vertex
must lie on the kept side (<= 0.5 mm) and at least one on the plane (|d| <= 0.5 mm). A global translation between the
exports (IFC base point) is estimated from joined parts first."""
import sys, numpy as np, collections
sys.path.insert(0, 'src'); sys.path.insert(0, '.')
import cache_eng, fittings, guid2
import ifcopenshell, ifcopenshell.guid as ig, ifcopenshell.geom
f, ifc, eng = sys.argv[1:4]
data, db, pts, cs, lay, M = cache_eng.get(f, eng)
db.find_cut_links(M)
fi = ifcopenshell.open(ifc); st = ifcopenshell.geom.settings(); st.set(st.USE_WORLD_COORDS, True)
def gid(e):
    tag = getattr(e, 'Tag', None) or ''
    if tag.startswith('ID'): return tag[2:38].upper()
    g_ = ig.expand(e.GlobalId).upper(); return '%s-%s-%s-%s-%s' % (g_[:8], g_[8:12], g_[12:16], g_[16:20], g_[20:])
E = {gid(e): e for e in fi.by_type('IfcElement') if e.Representation}
G = guid2.scan(data); best = None
for off in (8, 16, 26, 24, 4, 10, 12, 20, 28, 32):
    k2g = {}
    for p, s in G:
        v = int.from_bytes(data[p - off:p - off + 4], 'little', signed=True); k2g.setdefault(v, s)
    n = sum(1 for m in M if k2g.get(m['seq']) in E)
    if best is None or n > best[0]: best = (n, off, k2g)
k2g = best[2]; print(eng, 'join', best[0], 'offset', best[1])
cache = {}
def verts(e):
    if e.id() not in cache:
        try:
            sh = ifcopenshell.geom.create_shape(st, e); V = np.array(sh.geometry.verts).reshape(-1, 3)
            cache[e.id()] = V * (1000.0 if np.abs(V).max() < 1e5 and np.abs(V).max() > 0 else 1.0)
        except Exception: cache[e.id()] = None
    return cache[e.id()]
# translation: median over joined beams of (IFC bbox centre - our O..E midpoint), using uncut members
sh = []
for m in M[:4000]:
    if m['cut'] or not m['prof']: continue
    e = E.get(k2g.get(m['seq']))
    if e is None or e.is_a() not in ('IfcBeam', 'IfcColumn'): continue
    V = verts(e)
    if V is None or not len(V): continue
    sh.append((V.min(0) + V.max(0)) / 2 - (m['O'] + m['E']) / 2)
    if len(sh) > 300: break
T = np.median(np.array(sh), 0) if sh else np.zeros(3)
T = np.where(np.abs(T) < 50, 0.0, T); print('translation', np.round(T, 1))
# rigid fit (rotation + translation) from joined uncut beam axes when the exports are not aligned
import ifcopenshell.util.placement as up, ifcopenshell.util.unit as uu
sc_ = uu.calculate_unit_scale(fi) * 1000
A_, B_ = [], []
for m in M[:6000]:
    if m['cut'] or not m['prof']: continue
    e = E.get(k2g.get(m['seq']))
    if e is None or e.is_a() not in ('IfcBeam', 'IfcColumn'): continue
    it = e.Representation.Representations[0].Items[0]
    if not it.is_a('IfcExtrudedAreaSolid'): continue
    Mw = np.array(up.get_local_placement(e.ObjectPlacement)); Mw[:3, 3] *= sc_
    Pp = np.array(up.get_axis2placement(it.Position)); Pp[:3, 3] *= sc_; Gm = Mw @ Pp
    a = Gm[:3, 3]; b = a + Gm[:3, :3] @ np.array(it.ExtrudedDirection.DirectionRatios) * it.Depth * sc_
    if abs(np.linalg.norm(b - a) - m['L']) > 0.5: continue
    A_ += [m['O'], m['E']]; B_ += [b, a]          # Tekla IFC extrusion runs E -> O (see db1step placement)
R_ = np.eye(3); t_ = np.zeros(3)
if len(A_) >= 6:
    A_ = np.array(A_); B_ = np.array(B_)
    for it_ in range(3):
        ca, cb = A_.mean(0), B_.mean(0); H = (A_ - ca).T @ (B_ - cb); U, S_, Vt = np.linalg.svd(H); D_ = np.diag([1, 1, np.sign(np.linalg.det(Vt.T @ U.T))])
        R_ = Vt.T @ D_ @ U.T; t_ = cb - R_ @ ca
        res = np.linalg.norm((A_ @ R_.T + t_) - B_, axis=1); keep = res < max(1.0, np.percentile(res, 60))
        A_, B_ = A_[keep], B_[keep]
    print('rigid fit rot dev', round(float(np.degrees(np.arccos(min(1, (np.trace(R_) - 1) / 2)))), 4), 'deg  t', np.round(t_, 1), 'residual p50', round(float(np.median(np.linalg.norm((A_ @ R_.T + t_) - B_, axis=1))), 3))
def to_db1(V): return (V - t_) @ R_            # IFC world -> DB1 world
for t in (9, 12):
    F, info = fittings.find(db, cs, lay, M, t)
    c = collections.Counter()
    for seq, pl in F.items():
        e = E.get(k2g.get(seq))
        if e is None: c['unjoined'] += len(pl); continue
        V = verts(e)
        if V is None: c['no_ifc_geom'] += len(pl); continue
        V = to_db1(V)
        m = next(x for x in M if x['seq'] == seq); mid = m['O'] + m['x'] * m['L'] / 2
        for P, nrm in pl:
            nout = nrm if t == 12 else (-nrm if float((mid - P) @ nrm) > 0 else nrm)
            d = (V - P) @ nout
            c['planes'] += 1; c['ok'] += bool(d.max() < 0.5 and np.abs(d).min() < 0.5)
    print(eng, 'type', t, info.get('fittings'), dict(c), flush=True)
