import sys, numpy as np, collections, pickle, json
sys.path.insert(0, 'src'); sys.path.insert(0, '.')
import cache_eng, guid2
import ifcopenshell, ifcopenshell.util.placement as up, ifcopenshell.util.unit as uu, ifcopenshell.guid as ig
f, ifc, eng = sys.argv[1:4]
data, db, pts, cs, lay, M = cache_eng.get(f, eng)
fi = ifcopenshell.open(ifc); sc = uu.calculate_unit_scale(fi) * 1000
def gid(e):
    tag = getattr(e, 'Tag', None) or ''
    if tag.startswith('ID'): return tag[2:38].upper()
    g_ = ig.expand(e.GlobalId).upper(); return '%s-%s-%s-%s-%s' % (g_[:8], g_[8:12], g_[12:16], g_[16:20], g_[20:])
E = {gid(e): e for e in fi.by_type('IfcElement') if e.Representation}
G = guid2.scan(data); k2g = {}
for p, s in G:
    v = int.from_bytes(data[p - 26:p - 22], 'little', signed=True); k2g.setdefault(v, s)
def ifc_axis(e):
    Mw = np.array(up.get_local_placement(e.ObjectPlacement)); Mw[:3, 3] *= sc
    it = e.Representation.Representations[0].Items[0]; ops = []
    while it.is_a('IfcBooleanResult'): ops.append(it.SecondOperand); it = it.FirstOperand
    P = np.array(up.get_axis2placement(it.Position)); P[:3, 3] *= sc; Gm = Mw @ P
    d = np.array(it.ExtrudedDirection.DirectionRatios); a = Gm[:3, 3]; b = a + Gm[:3, :3] @ d * it.Depth * sc
    return a, b, ops, Mw
n = 0
for m in M:
    if m['cut']: continue
    e = E.get(k2g.get(m['seq']))
    if e is None or e.is_a() not in ('IfcBeam', 'IfcColumn', 'IfcMember'): continue
    a, b, ops, Mw = ifc_axis(e)
    x = m['x']
    ta, tb = sorted([float((a - m['O']) @ x), float((b - m['O']) @ x)])
    if abs(ta) < 1 and abs(tb - m['L']) < 1: continue
    n += 1
    if n > 4: break
    print('\nseq', m['seq'], m['prof'], 'L', round(m['L'], 1), 'start off', round(ta, 2), 'end off', round(tb - m['L'], 2), 'ops', [o.is_a() for o in ops])
    for o in ops[:4]:
        if o.is_a('IfcHalfSpaceSolid') or o.is_a('IfcPolygonalBoundedHalfSpace') or o.is_a('IfcBoxedHalfSpace'):
            pl = o.BaseSurface.Position; Pp = np.array(up.get_axis2placement(pl)); Pp[:3, 3] *= sc; W = Mw @ Pp
            nrm = W[:3, 2] * (1 if o.AgreementFlag else -1); org = W[:3, 3]
            print('   halfspace plane origin along axis', round(float((org - m['O']) @ x), 2), 'normal.x', round(float(nrm @ x), 3))
        else:
            print('   op', o.is_a(), str(o)[:120])
    # all records referencing this seq
    hits = collections.Counter()
    for s_, recs in db.runs:
        for fld in range(13, min(s_, 80) - 3, 4):
            v = db.I(recs + fld); idx = np.nonzero(v == m['seq'])[0]
            for i in idx: hits[(s_, fld, int(db.I([int(recs[i]) + 13])[0]) if s_ == 69 else None)] += 1
    print('   referenced by (stride, field, type)', hits.most_common(10))
