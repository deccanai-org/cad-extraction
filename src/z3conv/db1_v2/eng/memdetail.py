import sys, pickle, numpy as np, collections, os
sys.path.insert(0, 'src'); sys.path.insert(0, '.')
from db1dec import load
import guid2, ifcopenshell, ifcopenshell.util.placement as up, ifcopenshell.util.unit as uu, ifcopenshell.guid as ig
f, ifc, mp = sys.argv[1:4]
data = load(f); M = pickle.load(open(mp, 'rb'))
if isinstance(M, dict):   # dump_members.py format
    M = [(q[0], q[1], q[2], q[3], float(np.linalg.norm(np.asarray(q[3]) - np.asarray(q[2]))), None, q[4]) for q in M['M'] if not q[5]]
fi = ifcopenshell.open(ifc); sc = uu.calculate_unit_scale(fi) * 1000
T = {}
for e in fi.by_type('IfcElement'):
    if not e.Representation: continue
    tag = getattr(e, 'Tag', None) or ''
    if tag.startswith('ID'): g = tag[2:38].upper()
    else:
        g_ = ig.expand(e.GlobalId).upper(); g = '%s-%s-%s-%s-%s' % (g_[:8], g_[8:12], g_[12:16], g_[16:20], g_[20:])
    Mw = np.array(up.get_local_placement(e.ObjectPlacement)); Mw[:3, 3] *= sc
    for r in e.Representation.Representations:
        if r.RepresentationIdentifier != 'Body': continue
        it = r.Items[0]; bool_ = False
        while True:
            if it.is_a('IfcMappedItem'): it = it.MappingSource.MappedRepresentation.Items[0]
            elif it.is_a('IfcBooleanResult'): it = it.FirstOperand; bool_ = True
            else: break
        if it.is_a('IfcExtrudedAreaSolid'):
            P = np.array(up.get_axis2placement(it.Position)); P[:3, 3] *= sc; G = Mw @ P
            d = np.array(it.ExtrudedDirection.DirectionRatios); a = G[:3, 3]; b = a + G[:3, :3] @ d * it.Depth * sc
            T[g] = dict(cls=e.is_a(), a=a, b=b, L=it.Depth * sc, prof=it.SweptArea.ProfileName, boolean=bool_)
        break
G = guid2.scan(data); seqs = set(m[0] for m in M); best = None
for off in range(4, 80):
    k2g = {}
    for p, s in G:
        v = int.from_bytes(data[p - off:p - off + 4], 'little', signed=True); k2g.setdefault(v, s)
    n = sum(1 for m in M if k2g.get(m[0]) in T)
    if best is None or n > best[0]: best = (n, off, k2g)
n, off, k2g = best; print('join', n, 'offset', off)
rows = []
for seq, prof, O, E, Lm, x, y, *_ in M:
    t = T.get(k2g.get(seq))
    if not t or t['cls'] not in ('IfcBeam', 'IfcColumn', 'IfcMember'): continue
    O = np.asarray(O); E = np.asarray(E); xx = (E - O) / np.linalg.norm(E - O)
    def ld(p): r = p - O; return float(np.linalg.norm(r - (r @ xx) * xx))
    ta, tb = sorted([float((t['a'] - O) @ xx), float((t['b'] - O) @ xx)])
    rows.append((max(ld(t['a']), ld(t['b'])), ta, tb - Lm, t['L'] - Lm, prof, t['prof'], t['boolean'], _[-1] if _ else None))
R = np.array([r[:4] for r in rows]); col = R[:, 0] < 1
print('members', len(R), 'collinear<1mm', round(col.mean(), 3), 'start<1', round((np.abs(R[:, 1]) < 1).mean(), 3), 'end<1', round((np.abs(R[:, 2]) < 1).mean(), 3), 'both', round(((np.abs(R[:, 1]) < 1) & (np.abs(R[:, 2]) < 1)).mean(), 3))
if col.any(): print('collinear: start offs pct', np.round(np.percentile(R[col][:, 1], [5, 25, 50, 75, 95]), 1), 'end offs', np.round(np.percentile(R[col][:, 2], [5, 25, 50, 75, 95]), 1))
print('non-collinear dist pct', np.round(np.percentile(R[~col][:, 0], [5, 25, 50, 75, 95]), 1) if (~col).any() else None)
print('examples', [tuple(np.round(r[:4], 1)) + r[4:] for r in rows[:12]])
print('boolean share', np.mean([r[6] for r in rows]))

fl = collections.Counter(); 
for r in rows:
    ex = abs(r[1]) < 1 and abs(r[2]) < 1
    fl[(r[7], ex, r[6])] += 1
print('by (flag, exact, boolean)', sorted(fl.items(), key=lambda x: -x[1]))
