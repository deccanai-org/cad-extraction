"""secck.py KIT DB1 IFC OUT.json : 'AxB' panels (parametric_panel) and studs (parametric_stud_shank) as written vs Tekla's own IFC export
(GUID join, new engines). Panel: which world axis carries the first number A in Tekla's IfcRectangleProfileDef vs the writer (YDim = A along
the part y). Stud: Tekla's body items (a head would be a second item / non-circle), radius and depth vs the writer. Control: catalog
I / RHS sections (writer frame sanity)."""
import sys, os, re, json, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db1dec import *
import db1step
from guid2 import guid_keys
import ifcopenshell, ifcopenshell.util.placement as up, ifcopenshell.util.unit as uu
p, ifcp, outp = sys.argv[2:5]
L_ = json.load(open(os.path.join(KIT, 'layouts.json'))); VA = [v['layout'] for v in L_.values() if v.get('layout')]
data = load(p); eng = re.search(rb'(\d+\.\d+)', data[:16]).group(1).decode()
res = dict(db1=p, ifc=ifcp, engine=eng)
cat = json.load(open(os.path.join(KIT, 'tekla_profiles.json')))
if float(eng) < 7.5:
    import db1old
    M = [m for m in db1old.read(data, float(eng))[0] if m.get('axis_ok') is not False and not m.get('cut')]
    for m in M: m['seq'] = m['pid']
    class _S: pass
    db = _S(); db.b = data; db.gkeys = np.array(sorted({m['pid'] for m in M}), np.int64)
    GK, back, _ = guid_keys(db, db.gkeys)
else:
    db, pts, cs, lay = decode(data, (L_.get(eng) or {}).get('layout'), VA, len(data) < 20_000_000); M = members(db, pts, cs, lay)
    GK, back, _ = guid_keys(db)
K2G = {}
for g_, k_ in GK.items(): K2G.setdefault(k_, g_)
f = ifcopenshell.open(ifcp); sc = uu.calculate_unit_scale(f) * 1000.0
byg = {}
for e in f.by_type('IfcElement'):
    t = (getattr(e, 'Tag', None) or '')
    if t.startswith('ID'): byg[t[2:38].upper()] = e
res.update(guid_join=back, ifc_tagged=len(byg))
def body_items(e):
    its = []
    for r in (e.Representation.Representations if e.Representation else []):
        if (r.RepresentationIdentifier or '') not in ('Body', ''): continue
        for it in r.Items:
            while it.is_a('IfcBooleanResult'): it = it.FirstOperand
            if it.is_a('IfcMappedItem'):
                its += list(it.MappingSource.MappedRepresentation.Items)
            else: its.append(it)
    return its
def axes(e, sol):
    Mw = np.array(up.get_local_placement(e.ObjectPlacement)); Pp = np.array(up.get_axis2placement(sol.Position)); W = Mw @ Pp
    pr = sol.SweptArea; R2 = np.eye(2)
    if getattr(pr, 'Position', None) is not None and pr.Position.RefDirection is not None:
        rd = np.array(pr.Position.RefDirection.DirectionRatios[:2], float); rd /= np.linalg.norm(rd); R2 = np.array([[rd[0], -rd[1]], [rd[1], rd[0]]])
    def w(v2):
        t2 = R2 @ np.asarray(v2, float); t = W[:3, 0] * t2[0] + W[:3, 1] * t2[1]; return t / np.linalg.norm(t)
    ed = np.asarray(sol.ExtrudedDirection.DirectionRatios, float); ed = W[:3, :3] @ ed; ed /= np.linalg.norm(ed)
    return w((1, 0)), w((0, 1)), ed
C = collections.Counter(); EX = collections.defaultdict(list); ROWS = []; MC = collections.Counter(); MROWS = []; nmesh = [0]
import ifcopenshell.geom
_gs = ifcopenshell.geom.settings(); _gs.set(_gs.USE_WORLD_COORDS, True)
def mesh(e):
    sh = ifcopenshell.geom.create_shape(_gs, e)
    return np.array(sh.geometry.verts).reshape(-1, 3) * 1000.0
ctrl = 0
for m in M:
    k, v, how = db1step.section_for(m.get('prof'), cat)
    isctl = how == 'catalog' and k in ('I', 'RHS', 'U') and ctrl < 400
    if how not in ('parametric_panel', 'parametric_stud_shank') and not isctl: continue
    tag = 'control' if isctl else how
    e = byg.get(K2G.get(m['seq']))
    if e is None: C[(tag, 'no_ifc_join')] += 1; continue
    if isctl: ctrl += 1
    o, Z, X = db1step.IfcOut.member_frame(m); Z = np.asarray(Z, float); X = np.asarray(X, float); Y = np.cross(Z, X)
    if how in ('parametric_panel', 'parametric_stud_shank') and nmesh[0] < 6000:
        try:
            Vw = mesh(e); nmesh[0] += 1
        except Exception:
            Vw = None
        if Vw is not None and len(Vw) >= 4:
            t = Vw @ Z; px = Vw @ X; py = Vw @ Y
            rec = dict(prof=m['prof'], tag=tag, eclass=e.is_a(), items=sorted(collections.Counter(it.is_a() for it in body_items(e)).items()),
                       rX=float(px.max() - px.min()), rY=float(py.max() - py.min()), rZ=float(t.max() - t.min()), L=float(m['L']), v=[float(x) for x in v])
            if how == 'parametric_panel':
                A, B = v[1], v[0]
                if abs(A - B) < 1e-6: mk = 'square'
                elif abs(rec['rX'] - B) < 1.0 and abs(rec['rY'] - A) < 1.0: mk = 'A_along_y_matches'
                elif abs(rec['rX'] - A) < 1.0 and abs(rec['rY'] - B) < 1.0: mk = 'rot90'
                else: mk = 'extents_other'
                rec['mk'] = mk; MC[(tag, mk, 'len_ok' if abs(rec['rZ'] - m['L']) < 1.0 else 'len_differs')] += 1
            else:
                Q = np.stack([px, py], 1); c0 = Q.mean(0); rad = np.linalg.norm(Q - c0, axis=1)
                lo, hi = t.min(), t.max(); mid = (t > lo + 0.25 * (hi - lo)) & (t < hi - 0.25 * (hi - lo))
                rs = float(np.median(rad[mid])) if mid.any() else float(np.median(rad))
                big = t[rad > rs + 0.75]
                rec.update(r_shank=rs, r_max=float(rad.max()), head_len=float(big.max() - big.min()) if len(big) else 0.0, r_dec=float(v[0]))
                mk = ('no_head' if rec['r_max'] <= rs + 0.75 else 'head') + ('_r_ok' if abs(rs - v[0]) < 0.5 else '_r_differs') + ('_len_ok' if abs(rec['rZ'] - m['L']) < 1.0 else '_len_differs')
                rec['mk'] = mk; MC[(tag, mk)] += 1
            if len(MROWS) < 4000: MROWS.append(rec)
    its = body_items(e)
    sols = [it for it in its if it.is_a('IfcExtrudedAreaSolid')]
    kinds = collections.Counter(it.is_a() for it in its)
    if len(sols) != 1 or len(its) != 1:
        key = (tag, 'ifc_items', tuple(sorted(kinds.items())), e.is_a()); C[key] += 1
        if len(EX[key]) < 3: EX[key].append(m.get('prof'))
        continue
    sol = sols[0]; pr = sol.SweptArea
    o, Z, X = db1step.IfcOut.member_frame(m); Z = np.asarray(Z, float); X = np.asarray(X, float); Y = np.cross(Z, X)
    ax, ay, ed = axes(e, sol)
    zok = abs(abs(float(ed @ Z)) - 1) < 1e-3
    dep = float(sol.Depth) * sc
    if how == 'parametric_panel':
        if not pr.is_a('IfcRectangleProfileDef'): key = (tag, 'ifc_profile', pr.is_a()); C[key] += 1; EX[key].append(m['prof']) if len(EX[key]) < 3 else 0; continue
        A, B = v[1], v[0]                                   # writer: XDim = v[0] = B along X, YDim = v[1] = A along Y
        xd, yd = pr.XDim * sc, pr.YDim * sc
        if abs(A - B) < 1e-6: key = (tag, 'square', 'dims_ok' if abs(xd - A) < 0.6 and abs(yd - A) < 0.6 else 'dims_differ')
        elif abs(xd - A) < 0.6 and abs(yd - B) < 0.6: a_ifc = ax; key = None
        elif abs(yd - A) < 0.6 and abs(xd - B) < 0.6: a_ifc = ay; key = None
        else: key = (tag, 'dims_differ')
        if key is None:
            c_ = abs(float(a_ifc @ Y))
            key = (tag, 'A_axis_matches' if c_ > 1 - 1e-3 else ('A_axis_rot90' if abs(float(a_ifc @ X)) > 1 - 1e-3 else 'A_axis_other'),
                   'z_ok' if zok else 'z_differs', 'len_ok' if abs(dep - m['L']) < 1.0 else 'len_differs')
        C[key] += 1
        if len(EX[key]) < 4: EX[key].append(m['prof'])
        ROWS.append(dict(prof=m['prof'], key=list(key), xd=xd, yd=yd, dep=dep, L=m['L']))
    elif how == 'parametric_stud_shank':
        if pr.is_a('IfcCircleProfileDef'):
            r_ = pr.Radius * sc
            key = (tag, 'ifc_single_circle_extrusion', 'r_ok' if abs(r_ - v[0]) < 0.3 else 'r_%.2f_vs_%.2f' % (v[0], r_), 'z_ok' if zok else 'z_differs',
                   'len_ok' if abs(dep - m['L']) < 1.0 else 'len_differs', e.is_a())
        else:
            key = (tag, 'ifc_profile', pr.is_a(), e.is_a())
        C[key] += 1
        if len(EX[key]) < 4: EX[key].append(m['prof'])
        ROWS.append(dict(prof=m['prof'], key=list(key), dep=dep, L=m['L']))
    else:
        dims_ok = pr.is_a() in ('IfcIShapeProfileDef', 'IfcRectangleHollowProfileDef', 'IfcUShapeProfileDef')
        key = (tag, 'z_ok' if zok else 'z_differs', 'len_ok' if abs(dep - m['L']) < 1.0 else 'len_differs')
        if pr.is_a('IfcIShapeProfileDef'):
            key = key + ('depth_axis_matches' if abs(float(ay @ Y)) > 1 - 1e-3 else ('depth_axis_rot90' if abs(float(ay @ X)) > 1 - 1e-3 else 'depth_axis_other'),)
        C[key] += 1
res['counts'] = [[list(k), n, EX.get(k)] for k, n in C.most_common()]
res['rows'] = ROWS[:3000]; res['mesh_counts'] = [[list(k), n] for k, n in MC.most_common()]; res['mesh_rows'] = MROWS
json.dump(res, open(outp, 'w'), default=float)
print(os.path.basename(p), eng, back)
for k, n in C.most_common(8): print('  ', n, k, EX.get(k))
for k, n in MC.most_common(8): print('  M', n, k)
