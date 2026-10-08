"""validate a DB1 decode against the Tekla IFC export of the same model, joined by GUID.
members (IfcBeam/IfcColumn/IfcMember extrusions): profile name equal, axis ends within 1 mm (either direction);
contour plates (IfcPlate with an arbitrary profile): mid-plane outline centroid within 1 mm, area within 1 %.
usage: validate.py DB1 IFC ENGINE [srcdir]"""
import sys, json, collections, re, os, time
import numpy as np
SRC = sys.argv[4] if len(sys.argv) > 4 else 'src'
sys.path.insert(0, SRC); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db1dec; from db1dec import *
import guid2, ifcopenshell, ifcopenshell.util.placement as up, ifcopenshell.util.unit as uu
L = json.load(open(os.path.join(SRC, 'layouts.json'))); VA = [v['layout'] for v in L.values() if v.get('layout')]
f, ifc, eng = sys.argv[1:4]
t0 = time.time()
import cache_eng
data, db, pts, cs, lay, M = cache_eng.get(f, eng, SRC)
print('decode', round(time.time() - t0), 's members', len(M), 'lay', {k: lay.get(k) for k in ('stride', 'attr_stride', 'prof_off', 'rest_ref', 'fast', 'semi')} if lay else None)
fi = ifcopenshell.open(ifc); sc = uu.calculate_unit_scale(fi) * 1000
def poly_area_centroid(P):
    P = np.asarray(P); x, y = P[:, 0], P[:, 1]; x2, y2 = np.roll(x, -1), np.roll(y, -1)
    c = x * y2 - x2 * y; A = c.sum() / 2
    if abs(A) < 1e-9: return 0, P.mean(0)
    return A, np.array([((x + x2) * c).sum(), ((y + y2) * c).sum()]) / (6 * A)
T = {}
for e in fi.by_type('IfcElement'):
    tag = getattr(e, 'Tag', None) or ''
    if not e.Representation: continue
    if not tag.startswith('ID'):
        import ifcopenshell.guid as _ig
        g_ = _ig.expand(e.GlobalId).upper(); tag = 'ID%s-%s-%s-%s-%s' % (g_[:8], g_[8:12], g_[12:16], g_[16:20], g_[20:])
    Mw = np.array(up.get_local_placement(e.ObjectPlacement)); Mw[:3, 3] *= sc
    for r in e.Representation.Representations:
        if r.RepresentationIdentifier != 'Body': continue
        for it in r.Items:
            while True:
                if it.is_a('IfcMappedItem'): it = it.MappingSource.MappedRepresentation.Items[0]
                elif it.is_a('IfcBooleanResult'): it = it.FirstOperand
                else: break
            if not it.is_a('IfcExtrudedAreaSolid'): continue
            P = np.array(up.get_axis2placement(it.Position)); P[:3, 3] *= sc
            G = Mw @ P; d = np.array(it.ExtrudedDirection.DirectionRatios); Ld = it.Depth * sc
            a = G[:3, 3]; b = a + G[:3, :3] @ d * Ld
            rec = dict(cls=e.is_a(), prof=it.SweptArea.ProfileName, a=a, b=b, L=Ld)
            sa = it.SweptArea
            if sa.is_a('IfcArbitraryClosedProfileDef') and sa.OuterCurve.is_a('IfcPolyline'):
                pp = np.array([q.Coordinates[:2] for q in sa.OuterCurve.Points]) * sc
                mid = np.c_[pp, np.full(len(pp), 0.0)]
                W = (G[:3, :3] @ mid.T).T + G[:3, 3] + (G[:3, :3] @ d) * Ld / 2
                rec['outline_w'] = W; rec['thick'] = Ld
            T[tag[2:38].upper()] = rec; break
        break
print('ifc tagged elements', len(T), collections.Counter(v['cls'] for v in T.values()).most_common(6))
gm_all = guid2.scan(data)
seqset = set(m['seq'] for m in M); tagset = set(T)
top = []
for off in range(4, 80):
    hit = 0
    for g, s_ in gm_all:
        if s_ in tagset and int.from_bytes(data[g - off:g - off + 4], 'little', signed=True) in seqset: hit += 1
    top.append((off, hit))
top.sort(key=lambda x: -x[1]); print('join offsets', top[:4])
norm = lambda s: re.sub(r'\s+', '', (s or '').upper())
res = {}
for off, _ in top[:3]:
    key2g = {}
    for g, s in gm_all:
        v = int.from_bytes(data[g - off:g - off + 4], 'little', signed=True); key2g.setdefault(v, s)
    st = collections.Counter(); bad = []
    for m in M:
        if m.get('cut'): continue
        g = key2g.get(m['seq']); t = T.get(g)
        if t is None: st['unjoined'] += 1; continue
        st['joined'] += 1
        if t['cls'] in ('IfcBeam', 'IfcColumn', 'IfcMember') and 'outline_w' not in t:
            st['mem'] += 1
            st['mem_prof_eq'] += norm(t['prof']) == norm(m['prof'])
            dd = min(max(np.linalg.norm(t['a'] - m['O']), np.linalg.norm(t['b'] - m['E'])), max(np.linalg.norm(t['b'] - m['O']), np.linalg.norm(t['a'] - m['E'])))
            st['mem_axis_1mm'] += dd < 1.0
            if dd >= 1.0 and len(bad) < 5: bad.append((m['prof'], t['prof'], round(float(dd), 1)))
        elif 'outline_w' in t and m['prof'] and PLATE1_RE.match(m['prof']):
            st['plate'] += 1
            poly = db.polygon(lay, m)
            if not poly: st['plate_no_outline'] += 1; continue
            u, v = m['x'], m['y']
            Ai, Ci = poly_area_centroid(poly); Cw = m['O'] + u * Ci[0] + v * Ci[1]
            nrm = np.cross(u, v); W = t['outline_w']
            Aw = 0.5 * np.linalg.norm(sum(np.cross(W[i], W[(i + 1) % len(W)]) for i in range(len(W))))
            # IFC mid-plane centroid (area weighted) vs ours; our plate plane is through O (mid-plane)
            e1 = W[1] - W[0]; e1 /= np.linalg.norm(e1); nn = np.cross(W[1] - W[0], W[2] - W[0]); nn /= (np.linalg.norm(nn) or 1); e2 = np.cross(nn, e1)
            Q = np.c_[(W - W[0]) @ e1, (W - W[0]) @ e2]; Aq, Cq = poly_area_centroid(Q); Ctw = W[0] + e1 * Cq[0] + e2 * Cq[1]
            ok = np.linalg.norm(Ctw - Cw) < 1.0 and abs(abs(Ai) - abs(Aq)) <= 0.01 * abs(Aq)
            st['plate_ok'] += ok
    res[off] = (dict(st), bad)
    print('guid offset', off, dict(st)); print('   bad examples', bad)
if os.environ.get('DUMP'):
    off = top[0][0]; key2g = {}
    for g, s_ in gm_all:
        v = int.from_bytes(data[g - off:g - off + 4], 'little', signed=True); key2g.setdefault(v, s_)
    pc = collections.Counter()
    for m in M:
        t = T.get(key2g.get(m['seq']))
        if t and t['cls'] in ('IfcBeam', 'IfcColumn', 'IfcMember'): pc[(m['prof'], t['prof'], t['cls'], round(m['L']) == round(t['L']))] += 1
    for k_, v_ in pc.most_common(25): print(v_, k_)
if os.environ.get('MEMDETAIL'):
    off = top[0][0]; key2g = {}
    for g, s_ in gm_all:
        v = int.from_bytes(data[g - off:g - off + 4], 'little', signed=True); key2g.setdefault(v, s_)
    rows = []
    for m in M:
        t = T.get(key2g.get(m['seq']))
        if not t or t['cls'] not in ('IfcBeam', 'IfcColumn', 'IfcMember') or 'outline_w' in t: continue
        x = m['E'] - m['O']; x /= np.linalg.norm(x)
        def ld(p): r = p - m['O']; return float(np.linalg.norm(r - (r @ x) * x))
        coll = max(ld(t['a']), ld(t['b']))
        ta, tb = sorted([float((t['a'] - m['O']) @ x), float((t['b'] - m['O']) @ x)])
        rows.append((coll, ta, tb - m['L'], t['L'] - m['L'], m['prof']))
    R = np.array([r[:4] for r in rows])
    print('members', len(R), 'collinear<1mm', (R[:, 0] < 1).mean(), 'start within 1', (np.abs(R[:, 1]) < 1).mean(), 'end within 1', (np.abs(R[:, 2]) < 1).mean(), 'both', ((np.abs(R[:, 1]) < 1) & (np.abs(R[:, 2]) < 1)).mean())
    print('collinear but ends differ: start offs', np.round(np.percentile(R[R[:, 0] < 1][:, 1], [5, 25, 50, 75, 95]), 1), 'end offs', np.round(np.percentile(R[R[:, 0] < 1][:, 2], [5, 25, 50, 75, 95]), 1))
    import collections as C_
    print('non-collinear examples', [tuple(np.round(r[:4], 1)) + (r[4],) for r in rows if r[0] >= 1][:8])
