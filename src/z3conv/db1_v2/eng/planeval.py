"""validate decoded cut planes (relation types 9 / 12 / 34) against the Tekla IFC half-space clippings of the same part (GUID join).
A decoded plane matches when an IFC IfcHalfSpaceSolid of that part has a parallel normal (|cos| > 0.9999) and lies within 0.5 mm."""
import sys, numpy as np, collections, os
sys.path.insert(0, 'src'); sys.path.insert(0, '.')
import cache_eng, guid2, fittings
import ifcopenshell, ifcopenshell.util.placement as up, ifcopenshell.util.unit as uu, ifcopenshell.guid as ig
f, ifc, eng = sys.argv[1:4]
data, db, pts, cs, lay, M = cache_eng.get(f, eng)
db.find_cut_links(M)
fi = ifcopenshell.open(ifc); sc = uu.calculate_unit_scale(fi) * 1000
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
k2g = best[2]
def ifc_planes(e):
    Mw = np.array(up.get_local_placement(e.ObjectPlacement)); Mw[:3, 3] *= sc
    out = []
    for r in e.Representation.Representations:
        if r.RepresentationIdentifier != 'Body': continue
        stack = list(r.Items)
        while stack:
            it = stack.pop()
            if it.is_a('IfcBooleanResult'):
                stack += [it.FirstOperand, it.SecondOperand]
            elif it.is_a('IfcHalfSpaceSolid'):
                Pp = np.array(up.get_axis2placement(it.BaseSurface.Position)); Pp[:3, 3] *= sc; W = Mw @ Pp
                out.append((W[:3, 3], W[:3, 2], -W[:3, 2] if it.AgreementFlag else W[:3, 2]))
    return out
# global translation between the exports (Tekla IFC may be shifted by a base point): median over joined members' plane-free check
res = {}
for t in (9, 12, 34):
    F, info = fittings.find(db, cs, lay, M, t)
    st = collections.Counter()
    for seq, planes in F.items():
        e = E.get(k2g.get(seq))
        if e is None: st['part_unjoined'] += len(planes); continue
        IP = ifc_planes(e)
        m = next(x for x in M if x['seq'] == seq); mid = m['O'] + m['x'] * m['L'] / 2
        for P, n in planes:
            hit = [(P2, n2, r2) for P2, n2, r2 in IP if abs(float(n @ n2)) > 0.9999 and abs(float((P - P2) @ n2)) < 0.5]
            st['planes'] += 1; st['matched'] += bool(hit)
            if hit:
                n_out = -n if float((mid - P) @ n) > 0 else n          # rule: remove the side away from the part middle
                st['side_agrees'] += float(n_out @ hit[0][2]) > 0
                st['plus_n_removed'] += float(n @ hit[0][2]) > 0
    res[t] = (info.get('fittings'), dict(st))
    print(eng, 'type', t, 'decoded planes', info.get('fittings'), dict(st), flush=True)
