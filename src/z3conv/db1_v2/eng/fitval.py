"""validate fittings: per member end, ours (with fitting trims) vs the Tekla IFC extrusion ends (GUID join)"""
import sys, numpy as np, collections
sys.path.insert(0, 'src'); sys.path.insert(0, '.')
import cache_eng, guid2, fittings
import ifcopenshell, ifcopenshell.util.placement as up, ifcopenshell.util.unit as uu, ifcopenshell.guid as ig
f, ifc, eng = sys.argv[1:4]
data, db, pts, cs, lay, M = cache_eng.get(f, eng)
db.find_cut_links(M)
import os
FT = os.environ.get('FT'); F, info = fittings.find(db, cs, lay, M, int(FT) if FT else None); print('fittings', info)
fi = ifcopenshell.open(ifc); sc = uu.calculate_unit_scale(fi) * 1000
def gid(e):
    tag = getattr(e, 'Tag', None) or ''
    if tag.startswith('ID'): return tag[2:38].upper()
    g_ = ig.expand(e.GlobalId).upper(); return '%s-%s-%s-%s-%s' % (g_[:8], g_[8:12], g_[12:16], g_[16:20], g_[20:])
E = {gid(e): e for e in fi.by_type('IfcElement') if e.Representation}
G = guid2.scan(data); seqs = set(m['seq'] for m in M); best = None
for off in (8, 16, 26, 4, 10, 12, 20, 24, 28, 32):
    k2g = {}
    for p, s in G:
        v = int.from_bytes(data[p - off:p - off + 4], 'little', signed=True); k2g.setdefault(v, s)
    n = sum(1 for m in M if k2g.get(m['seq']) in E)
    if best is None or n > best[0]: best = (n, off, k2g)
k2g = best[2]; print('join', best[0], 'offset', best[1])
st = collections.Counter(); ex = []
for m in M:
    if m['cut']: continue
    e = E.get(k2g.get(m['seq']))
    if e is None or e.is_a() not in ('IfcBeam', 'IfcColumn', 'IfcMember'): continue
    Mw = np.array(up.get_local_placement(e.ObjectPlacement)); Mw[:3, 3] *= sc
    it = e.Representation.Representations[0].Items[0]
    while it.is_a('IfcBooleanResult'): it = it.FirstOperand
    if it.is_a('IfcMappedItem') or not it.is_a('IfcExtrudedAreaSolid'): continue
    P = np.array(up.get_axis2placement(it.Position)); P[:3, 3] *= sc; Gm = Mw @ P
    d = np.array(it.ExtrudedDirection.DirectionRatios); a = Gm[:3, 3]; b = a + Gm[:3, :3] @ d * it.Depth * sc
    x = m['x']; ta, tb = sorted([float((a - m['O']) @ x), float((b - m['O']) @ x)])
    r = m['O'] - a; coll = np.linalg.norm(np.cross(b - a, r)) / max(np.linalg.norm(b - a), 1e-9)
    if coll > 1: st['not_collinear'] += 1; continue
    t0, t1, obl = fittings.trim(m, F.get(m['seq'], []))
    before = abs(ta) < 1 and abs(tb - m['L']) < 1
    if obl:
        # oblique fitting: Tekla shortens the extrusion to the plane's furthest reach; judge only the perpendicular ends
        st['oblique'] += 1
    after0 = abs(ta - t0) < 1; after1 = abs(tb - t1) < 1
    st['members'] += 1; st['exact_before'] += before; st['exact_after'] += after0 and after1
    st['ends'] += 2; st['ends_ok_after'] += after0 + after1; st['ends_ok_before'] += (abs(ta) < 1) + (abs(tb - m['L']) < 1)
    st['with_fittings'] += bool(F.get(m['seq']))
    if not (after0 and after1) and len(ex) < 8: ex.append((m['seq'], m['prof'], round(ta, 2), round(tb - m['L'], 2), round(t0, 2), round(t1 - m['L'], 2), len(F.get(m['seq'], [])), len(obl)))
print(dict(st)); print('mismatch examples (seq, prof, ifc start, ifc end-L, our t0, our t1-L, n_fit, n_obl)'); [print('  ', e) for e in ex]
