"""make_spec.py ID PROFILE WINDOW_MM OUT.json [elev azim] : before/after render spec for the parent part of PROFILE with the most cuts
after the patch (kitp2) and the cut bodies that the deployed kit (kit2) wrote as steel parts"""
import sys, json, gzip, numpy as np
import ifcopenshell, ifcopenshell.geom
W = '/work/agentwork/cut-not-applied'
ID, PROF, WIN, OUT = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
el, az = (float(sys.argv[5]), float(sys.argv[6])) if len(sys.argv) > 6 else (20, -60)
def plist(v): return {p[0]: p for p in json.load(gzip.open(f'{W}/pipes2/{v}/{ID}/convert.json.parts.json.gz', 'rt'))}
AFTER = __import__('os').environ.get('AFTER', 'kitp2')
A, B = plist('kit2'), plist(AFTER)
dec = json.load(open(f'{W}/dec/after/{ID}.json')); rel = {int(k): v for k, v in dec['cut_rel'].items()}
cand = [(p[6] - A[pid][6], p[6], pid) for pid, p in B.items() if p[1] == PROF and p[3] == 'written' and pid in A and A[pid][3] == 'written']
_, nc, par = max(cand)
kids = [c for c in rel.get(par, []) if c in A and A[c][3] == 'written']
S = ifcopenshell.geom.settings(); S.set('use-world-coords', True)
f = ifcopenshell.open(f'{W}/pipes2/{AFTER}/{ID}/model.ifc')
v = np.array(ifcopenshell.geom.create_shape(S, f.by_guid(B[par][5])).geometry.verts).reshape(-1, 3) * 1000.0
lo, hi = v.min(0), v.max(0); k = int(np.argmax(hi - lo)); c = (lo + hi) / 2
# window along the long axis: centred on the cut bodies the deployed kit wrote as steel (where the cuts are), else on the part end
fa = ifcopenshell.open(f'{W}/pipes2/kit2/{ID}/model.ifc'); cc = []
for ch in kids:
    try: cc.append(np.array(ifcopenshell.geom.create_shape(S, fa.by_guid(A[ch][5])).geometry.verts).reshape(-1, 3).mean(0) * 1000.0)
    except Exception: pass
if cc and __import__('os').environ.get('WIN_AT', 'cuts') == 'cuts':
    ck = np.array([x[k] for x in cc]); end = hi[k] if abs(np.median(ck) - hi[k]) < abs(np.median(ck) - lo[k]) else lo[k]
    sel = ck[np.abs(ck - end) < WIN] if np.any(np.abs(ck - end) < WIN) else ck
    ctr = float(np.clip(np.median(sel), lo[k] + WIN / 2 - 100, hi[k] - WIN / 2 + 100))
else:
    ctr = c[k]
crop = list(lo - 150) + list(hi + 150); crop[k] = ctr - WIN / 2; crop[k + 3] = ctr + WIN / 2
if len(sys.argv) <= 6:                       # look at the broad face: camera along the thinnest bbox axis, tilted 30 deg
    ext = hi - lo; t = int(np.argmin(ext)); o = [i for i in range(3) if i not in (t, k)][0]
    d = np.zeros(3); d[t] = np.cos(np.radians(30)); d[o] = np.sin(np.radians(30)); d[k] = 0.25; d /= np.linalg.norm(d)
    el = float(np.degrees(np.arcsin(d[2]))); az = float(np.degrees(np.arctan2(d[1], d[0])))
spec = {'title': f'{ID}  {PROF} part {par}: {nc} cuts after the patch (deployed kit: {A[par][6]} cuts, {len(kids)} cut bodies written as steel)',
        'panels': [{'label': 'before (deployed kit)', 'ifc': f'{W}/pipes2/kit2/{ID}/model.ifc', 'parts': [[A[par][5], 'part']] + [[A[c][5], 'phantom'] for c in kids]},
                   {'label': 'after (cut-not-applied patch)', 'ifc': f'{W}/pipes2/{AFTER}/{ID}/model.ifc', 'parts': [[B[par][5], 'part']]}],
        'crop': [float(x) for x in crop], 'elev': el, 'azim': az}
json.dump(spec, open(OUT, 'w')); print('spec', OUT, 'parent', par, 'cuts', nc, 'phantoms', len(kids), 'crop', np.round(crop, 0).tolist())
