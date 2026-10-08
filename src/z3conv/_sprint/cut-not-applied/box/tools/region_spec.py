"""region_spec.py ID PID HALF OUT.json : before/after render of every written part around decoded part PID (box of +-HALF mm around its
centre) - shows parts recovered by the patch (absent before) together with their cuts"""
import sys, json, gzip, numpy as np, ifcopenshell, ifcopenshell.geom
W = '/work/agentwork/cut-not-applied'; ID, PID, H, OUT = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
S = ifcopenshell.geom.settings(); S.set('use-world-coords', True)
def plist(v): return {p[0]: p for p in json.load(gzip.open(f'{W}/pipes2/{v}/{ID}/convert.json.parts.json.gz', 'rt'))}
A, B = plist('kit2'), plist('kitp2')
fb = ifcopenshell.open(f'{W}/pipes2/kitp2/{ID}/model.ifc')
v = np.array(ifcopenshell.geom.create_shape(S, fb.by_guid(B[PID][5])).geometry.verts).reshape(-1, 3) * 1000.0
c = (v.min(0) + v.max(0)) / 2; crop = list(c - H) + list(c + H)
def near(f, P):
    out = []
    for pid, p in P.items():
        if p[3] != 'written' or not p[5] or p[4] in ('bolt_group', 'holes_only_group'): continue
        try:
            vv = np.array(ifcopenshell.geom.create_shape(S, f.by_guid(p[5])).geometry.verts).reshape(-1, 3) * 1000.0
        except Exception: continue
        if np.all(vv.max(0) >= c - H) and np.all(vv.min(0) <= c + H): out.append([p[5], 'part' if (pid in A or f is fa) else 'part'])
    return out
fa = ifcopenshell.open(f'{W}/pipes2/kit2/{ID}/model.ifc')
pa = near(fa, A); pb = near(fb, B)
ph = {A[k][5] for k in A if k not in B and A[k][3] == 'written'}
pa = [[g, 'phantom' if g in ph else 'part'] for g, _ in pa]
spec = {'title': f'{ID}: parts within {int(H)} mm of part {PID} ({B[PID][1]}), deployed kit {len(pa)} parts, patched {len(pb)} parts',
        'panels': [{'label': 'before (deployed kit)', 'ifc': f'{W}/pipes2/kit2/{ID}/model.ifc', 'parts': pa},
                   {'label': 'after (cut-not-applied patch)', 'ifc': f'{W}/pipes2/kitp2/{ID}/model.ifc', 'parts': pb}],
        'crop': [float(x) for x in crop], 'auto_view': False, 'elev': 25, 'azim': -55}
json.dump(spec, open(OUT, 'w')); print('region', ID, PID, len(pa), len(pb))
