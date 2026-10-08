"""7.x: bolt groups are MM members; GUID join IFC fastener -> member; compare decoded positions (poly link) vs mesh truth"""
import sys, numpy as np, collections, re, ifcopenshell
from cache import *
from guidmap import db1_guids
import truthmesh
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
print('lay poly', {k: lay.get(k) for k in ('poly_field', 'poly_stride', 'poly_field2', 'poly_stride2', 'poly_ub', 'poly_vb', 'poly_cap', 'poly_ch')})
seqs = {m['seq']: m for m in M}
d = db.b
# generic GUID->key: find which int before the GUID string equals a member seq
RX = re.compile(rb'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}')
hits = collections.Counter(); found = []
for mm in RX.finditer(d):
    g = mm.start(); found.append((g, mm.group().decode().upper()))
sk = np.array(sorted(seqs), np.int64)
for back in range(4, 80, 1):
    v = np.array([int.from_bytes(d[g - back:g - back + 4], 'little', signed=True) for g, _ in found[:5000]])
    hits[back] = int(inkeys(sk, v).sum())
print('best back offsets', hits.most_common(4))
back = hits.most_common(1)[0][0]
G = {s: int.from_bytes(d[g - back:g - back + 4], 'little', signed=True) for g, s in found}
f = ifcopenshell.open(ifc)
fast = [(e, (e.Tag or '')[2:38].upper()) for e in f.by_type('IfcMechanicalFastener')]
pairs = [(e, seqs[G[t]]) for e, t in fast if t in G and G[t] in seqs]
print('fasteners', len(fast), 'joined to members', len(pairs), 'profiles', collections.Counter((m['prof'] or '')[:6] for e, m in pairs).most_common(5))
SENT = 2147483647
def positions(m):
    if not lay.get('poly_stride'): return None
    k = int(db.I([m['off'] + lay['poly_field']])[0]); S = lay['poly_stride']
    if lay.get('poly_field2'):
        r = int(db.lookup([k], S)[0]); 
        if r < 0: return None
        k = int(db.I([r + lay['poly_field2']])[0]); S = lay['poly_stride2']
    recs = db.lookup_all(k, S)
    if not recs: return None
    cap, ub, vb = lay['poly_cap'], lay['poly_ub'], lay['poly_vb']; A = 4 * cap
    byidx = {}
    for r in recs: byidx.setdefault(int(db.I([r + 13])[0]) if lay.get('poly_ch') else 0, r)
    out = []
    for i in range(len(byidx)):
        r = byidx.get(i)
        if r is None: break
        u = db.F(r + ub + 4 * np.arange(cap)); v = db.F(r + vb + 4 * np.arange(cap))
        if lay.get('poly_ch'):
            ty = db.I(r + ub + 5 * A + 4 * np.arange(cap)); e_ = np.nonzero(ty == SENT)[0]; n = int(e_[0]) if len(e_) else cap
        else:
            n = 1
            while n < cap and not (abs(u[n]) < 1e-3 and abs(v[n]) < 1e-3): n += 1
        out += [(float(u[j]), float(v[j])) for j in range(n)]
        if n < cap: break
    return out
st = collections.Counter(); ex = []
for e, m in pairs[:600]:
    try: V = truthmesh.mesh(e)
    except Exception: st['mesh_fail'] += 1; continue
    dd = float(e.NominalDiameter or 20)
    C = truthmesh.centres(V, m['O'], m['x'], m['y'], dd)
    P = positions(m)
    if P is None: st['no_positions'] += 1; continue
    if len(P) != len(C): st['count_mismatch'] += 1
    Pa = np.array(P); Ca = np.array([c[:2] for c in C])
    D = np.linalg.norm(Pa[:, None] - Ca[None], axis=2)
    ok = (D.min(1) < 1.0).all() and (D.min(0) < 1.0).all()
    st['exact' if ok else 'off'] += 1
    if not ok and len(ex) < 8: ex.append((m['prof'][:20], np.round(Pa[:4], 1).tolist(), np.round(Ca[:4], 1).tolist()))
print(st)
for x in ex: print(x)
