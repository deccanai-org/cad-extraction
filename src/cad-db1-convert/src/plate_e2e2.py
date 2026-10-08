import sys, re, json, pickle, collections, numpy as np; sys.path.insert(0,'src')
exec(open('src/plate_e2e.py').read().split('truth = ')[0])
from db1dec import *
tag, eng = sys.argv[1], sys.argv[2]
truth = [p for p in pickle.load(open(f'pairs/data/{tag}.ifc.plates.pkl', 'rb')) if p['cls'] == 'IfcPlate']
ours = [p for p in pickle.load(open(f'pairs/data/{tag}_t.ifc.plates.pkl', 'rb')) if p['cls'] == 'IfcPlate']
def corners(p):
    P = p['pts'][:-1] if np.linalg.norm(p['pts'][0] - p['pts'][-1]) < 1e-6 else p['pts']
    n = p['n'] / np.linalg.norm(p['n'])
    return np.concatenate([P, P + n * p['t']])
C = [corners(p) for p in ours]; own = np.concatenate([[i] * len(c) for i, c in enumerate(C)]); tree = cKDTree(np.concatenate(C))
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L[eng]['layout'],V,False)
M=members(db,pts,cs,lay); Os=np.array([m['O'] for m in M]); otree=cKDTree(Os)
res = collections.Counter(); why = collections.Counter()
for p in truth:
    mid = p['pts'][:-1] + p['n'] / np.linalg.norm(p['n']) * p['t'] / 2
    dm, jm = otree.query(mid)
    k = int(np.argmin(dm))
    if dm[k] >= 1.0: res['no_db1_member_origin_on_plate'] += 1; continue
    m = M[jm[k]]
    if not (m['prof'] and PLATE1_RE.match(m['prof'])): res['db1_member_not_contour:' + str(m['prof'])[:6]] += 1; continue
    Vv = corners(p); d, j = tree.query(Vv)
    if d.max() < 1.0: res['contour_reproduced'] += 1; continue
    res['contour_NOT_reproduced'] += 1
    why[(m['prof'], bool(m['cut']), db.polygon(lay, m) is not None, round(float(np.nanmin(d)),1))] += 1
print(tag, 'truth contour plates', len(truth), dict(res))
print(why.most_common(12))
# detail: first 8 contour plates not reproduced -> truth uv (member frame) vs our polygon
k=0
for p in truth:
    mid = p['pts'][:-1] + p['n'] / np.linalg.norm(p['n']) * p['t'] / 2
    dm, jm = otree.query(mid); i = int(np.argmin(dm))
    if dm[i] >= 1.0: continue
    m = M[jm[i]]
    if not (m['prof'] and PLATE1_RE.match(m['prof'])): continue
    d, j = tree.query(corners(p))
    if d.max() < 1.0: continue
    uv = [(round(float((q - m['O']) @ m['x']),1), round(float((q - m['O']) @ m['y']),1)) for q in mid]
    P = db.polygon(lay, m)
    print(m['prof'], 'L', round(m['L'],1), 'n_truth', len(uv), '\n  truth', uv, '\n  ours ', [(round(a,1),round(b,1)) for a,b in P] if P else None,
          '\n  normal·z', round(float(np.cross(m['x'],m['y']) @ (p['n']/np.linalg.norm(p['n']))),3), 't', round(p['t'],2))
    k += 1
    if k >= 8: break
