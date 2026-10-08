import sys, json, collections, numpy as np
sys.path.insert(0, '/opt/db1v2/src')
from db1dec import *
L = json.load(open('/opt/db1v2/layouts.json')); V = [v['layout'] for v in L.values() if v.get('layout')]
for tag in sys.argv[1:]:
    db, pts, cs, lay = decode(f'/opt/db1v2/pairs/{tag}.db1', L['8.53']['layout'], V, False)
    M = [m for m in members(db, pts, cs, lay) if not m['cut']]
    hz = [m for m in M if abs(m['x'][2]) < 0.1 and m['L'] > 500]
    yv = sum(1 for m in hz if abs(m['y'][2]) > 0.996) / max(1, len(hz))
    print(tag, 'members', len(M), 'horizontal', len(hz), 'web-vertical frac', round(yv, 3), {k: lay.get(k) for k in ('fast', 'semi', 'csys', 'csys_key', 'csys_stride', 'csys_k')})
