import sys, json, time, collections, numpy as np, re
sys.path.insert(0, 'src')
import db1dec
from db1dec import *
TOL = float(sys.argv[3]) if len(sys.argv) > 3 else 0.02
def ortho(v1, v2):
    return ((np.abs((v1 * v1).sum(1) - 1) < 1e-6) & (np.abs((v2 * v2).sum(1) - 1) < 1e-6) & (np.abs((v1 * v2).sum(1)) < TOL))
Db._orthonormal = staticmethod(ortho)
L = json.load(open('src/layouts.json')); VA = [v['layout'] for v in L.values() if v.get('layout')]
f = sys.argv[1]; eng = sys.argv[2]
t = time.time(); db, pts, cs, lay = decode(load(f), L[eng]['layout'], VA, False); print('decode', round(time.time() - t, 1))
print('lay', {k: v for k, v in (lay or {}).items() if k not in ('tried',)})
if lay and lay.get('csys') is not None:
    M = members(db, pts, cs, lay); print('members', len(M), 'prof', sum(1 for m in M if m['prof']), 'axis', db1dec._axis_agreement(db, pts, lay, M), 'webv', db1dec._web_vertical(M))
    print(collections.Counter(m['prof'] for m in M).most_common(12))
    # non-orthogonality stats among used csys
    C = next(c for c in cs if c['stride'] == lay['csys_stride'] and c['k'] == lay['csys_k'] and c['key'] == lay['csys_key'])
    dots = np.array([abs(C['map'][int(db.I([m['off'] + lay['csys']])[0])][0] @ C['map'][int(db.I([m['off'] + lay['csys']])[0])][1]) for m in M])
    print('dot stats: >1e-4', (dots > 1e-4).mean(), 'max', dots.max() if len(dots) else None, np.percentile(dots, [50, 90, 99]) if len(dots) else None)
