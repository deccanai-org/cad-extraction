"""spec2.py DIR_A DIR_B PID HALF OUT.json LABEL_A LABEL_B TITLE : render spec (render_pair.py) of part PID and its written neighbours
within +-HALF mm, pipeline output dirs A (before) and B (after)"""
import sys, json, gzip, numpy as np, ifcopenshell, ifcopenshell.geom
DA, DB, PID, H, OUT, LA, LB, TITLE = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4]), sys.argv[5], sys.argv[6], sys.argv[7], sys.argv[8]
S = ifcopenshell.geom.settings(); S.set('use-world-coords', True)
def plist(d): return {p[0]: p for p in json.load(gzip.open(f'{d}/convert.json.parts.json.gz', 'rt'))}
A, B = plist(DA), plist(DB); fa, fb = ifcopenshell.open(f'{DA}/model.ifc'), ifcopenshell.open(f'{DB}/model.ifc')
v = np.array(ifcopenshell.geom.create_shape(S, fb.by_guid(B[PID][5])).geometry.verts).reshape(-1, 3) * 1000.0
c = (v.min(0) + v.max(0)) / 2; crop = list(c - H) + list(c + H)
def near(f, P):
    out = []
    for pid, p in P.items():
        if p[3] != 'written' or not p[5] or p[4] in ('bolt_group', 'holes_only_group'): continue
        try: vv = np.array(ifcopenshell.geom.create_shape(S, f.by_guid(p[5])).geometry.verts).reshape(-1, 3) * 1000.0
        except Exception: continue
        if np.all(vv.max(0) >= c - H) and np.all(vv.min(0) <= c + H): out.append([p[5], 'part'])
    return out
if H > 0:
    pa, pb = near(fa, A), near(fb, B)
else:                      # HALF <= 0: the part alone, uncropped
    pa, pb = [[A[PID][5], 'part']], [[B[PID][5], 'part']]; crop = None
spec = {'title': TITLE, 'panels': [{'label': LA, 'ifc': f'{DA}/model.ifc', 'parts': pa}, {'label': LB, 'ifc': f'{DB}/model.ifc', 'parts': pb}],
        'crop': [float(x) for x in crop] if crop else None, 'auto_view': True}
json.dump(spec, open(OUT, 'w')); print('spec', PID, len(spec['panels'][0]['parts']), len(spec['panels'][1]['parts']))
