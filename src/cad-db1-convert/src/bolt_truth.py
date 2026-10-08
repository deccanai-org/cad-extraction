import sys, json, re, collections, numpy as np; sys.path.insert(0,'src')
import ifcopenshell, ifcopenshell.geom
from db1dec import *
tag, eng = sys.argv[1], sys.argv[2]
f = ifcopenshell.open(f'pairs/data/{tag}.ifc')
st = ifcopenshell.geom.settings(); st.set(st.USE_WORLD_COORDS, True)
verts = []
for e in f.by_type('IfcMechanicalFastener'):
    try:
        sh = ifcopenshell.geom.create_shape(st, e)
        v = np.array(sh.geometry.verts).reshape(-1, 3) * 1000.0 if max(abs(x) for x in sh.geometry.verts[:30]) < 1e4 else np.array(sh.geometry.verts).reshape(-1, 3)
        verts.append(v)
    except Exception as ex:
        pass
V = np.concatenate(verts); print('fastener verts', len(V))
L = json.load(open('layouts.json')); VA = [v['layout'] for v in L.values() if v.get('layout')]
db, pts, cs, lay = decode(f'pairs/data/{tag}.db1', L[eng]['layout'], VA, False)
M = members(db, pts, cs, lay)
bg = [m for m in M if m['prof'] and m['prof'].startswith('MM') and not m['cut']]
stats = collections.Counter(); ex = []
for m in bg[:400]:
    ref = int(db.I([m['off'] + lay['poly_field']])[0]); o = db.lookup_all(ref, lay['poly_stride'])
    if not o: stats['no_positions'] += 1; continue
    u = db.F(o[0] + lay['poly_ub'] + 4 * np.arange(10)); v = db.F(o[0] + lay['poly_vb'] + 4 * np.arange(10))
    n = 1
    while n < 10 and not (abs(u[n]) < 1e-3 and abs(v[n]) < 1e-3): n += 1
    d, Lb = [float(x) for x in re.findall(r'[\d.]+', m['prof'].split('/')[0])[:2]]
    z = np.cross(m['x'], m['y'])
    for i in range(n):
        P = m['O'] + m['x'] * u[i] + m['y'] * v[i]
        rel = V - P; t = rel @ z; r = np.linalg.norm(rel - np.outer(t, z), axis=1)
        sel = (r < 1.2 * d) & (np.abs(t) < 4 * Lb)
        if sel.sum() < 10: stats['no_fastener_here'] += 1; continue
        tt = t[sel]; stats['found'] += 1
        w = db.F(o[0] + lay['poly_ub'] + 80 + 4 * np.arange(10))          # candidate third array (u@ub, v@ub+40, w@ub+80)
        ex.append((round(d, 2), round(Lb, 2), round(float(tt.min()), 2), round(float(tt.max()), 2), m['prof'][:48], round(float(w[i]), 2), [round(float(q), 2) for q in db.F(o[0] + 13 + 4 * np.arange(82))[50:82]]))
print(stats); c = collections.Counter((a, b, lo, hi, w) for a, b, lo, hi, _, w, _t in ex)
for k, v in c.most_common(14): print(v, 'd', k[0], 'L', k[1], 't_min', k[2], 't_max', k[3], 'w', k[4])
print('record tail floats (idx50..81) for 3 bolts:'); [print('  ', e[0], e[1], e[2], e[3], e[6]) for e in ex[:3]]

