"""Instrumented v4 stage-2 run: capture SDS2 bolt records and hole stacks, then explain every nominal bolt
(nearest SDS2 bolt record: distance of its head to the stack axis / ends, diameter, axis angle).
usage: bolt_diag.py <job> <out.step> [decode dir]"""
import sys, os, collections, json
import numpy as np
DEC = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'v4', 'sds2-step-pipeline', 'decode')
sys.path.insert(0, DEC)
import to_step2 as T2, bolts as BR
CAP = {'recs': [], 'stacks': None, 'hw': None}
_mb = BR.member_bolts
def mb(job, n, frame=None):
    r = _mb(job, n, frame); CAP['recs'] += r; return r
BR.member_bolts = mb
_bs = T2.bolt_stacks
def bs(C, A, D, T, I):
    CAP['hw'] = (C, A, D, T, I); s = _bs(C, A, D, T, I); CAP['stacks'] = s; return s
T2.bolt_stacks = bs
ok, stats = T2.convert(sys.argv[1], sys.argv[2])
recs = CAP['recs']; stacks = CAP['stacks'] or []
print('records (before de-dup)', len(recs), 'stacks', len(stacks), 'bolts', stats.get('bolts_sds2'), stats.get('bolts_nominal'))
print('record layouts', collections.Counter(r['layout'] for r in recs), 'dias', collections.Counter(round(r['dia'], 4) for r in recs))
from scipy.spatial import cKDTree
hp = np.array([r['head'] for r in recs]) if recs else np.zeros((0, 3))
tree = cKDTree(hp) if len(hp) else None
rows = []
for si, (e, a, g, d) in enumerate(stacks):
    ends = [e, e + a * g]
    dist_end = min(tree.query(x)[0] for x in ends) if tree else None
    # nearest record head to the stack axis (lateral distance) within 12 in
    best = None
    if tree:
        for j in tree.query_ball_point(e + a * g / 2, 12.0):
            r = recs[j]; v = r['head'] - e
            lat = np.linalg.norm(np.cross(v, a)); ax = v @ a
            cosang = abs(r['axis'] @ a)
            k = (lat, j)
            if best is None or k < best[0]: best = (k, dict(lat=round(float(lat), 4), along=round(float(ax), 4), cos=round(float(cosang), 4), dia=r['dia'], grip=r['grip'], L=r['length'], member=r['member']))
    rows.append(dict(stack=si, entry=np.round(e, 3).tolist(), axis=np.round(a, 3).tolist(), grip=round(g, 4), dia=d, dist_to_nearest_head_at_end=None if dist_end is None else round(float(dist_end), 4), nearest_on_axis=best and best[1]))
covered = [r for r in rows if r['dist_to_nearest_head_at_end'] is not None and r['dist_to_nearest_head_at_end'] < 2e-3]
nom = [r for r in rows if r not in covered]
print('stacks covered by a record head at an end:', len(covered), ' nominal:', len(nom))
cat = collections.Counter()
for r in nom:
    b = r['nearest_on_axis']
    if b is None: cat['no record within 12 in'] += 1
    elif b['lat'] < 0.0625 and b['cos'] > 0.999: cat['record on the same axis, head not at a stack end'] += 1
    elif b['lat'] < 0.5: cat['record within 1/2 in of axis'] += 1
    else: cat['nearest record > 1/2 in off axis'] += 1
print('nominal stacks by nearest-record category:', dict(cat))
json.dump(dict(stats={k: v for k, v in stats.items()}, nominal=nom, covered=len(covered)), open(os.path.splitext(sys.argv[2])[0] + '_bolt_diag.json', 'w'), indent=1, default=str)
for r in nom[:12]: print(json.dumps(r))
