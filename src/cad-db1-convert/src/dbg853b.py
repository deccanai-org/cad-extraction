import sys, json, pickle, collections, numpy as np
sys.path.insert(0, '/opt/db1v2/src')
from db1dec import *
L = json.load(open('/opt/db1v2/layouts.json')); lay0 = L['8.53']['layout']
T = pickle.load(open('/opt/db1v2/pairs/8.53_0575f7270f.ifc.truth.pkl', 'rb'))
A = np.array([t['a'] for t in T]); B = np.array([t['b'] for t in T])
db = Db(load('/opt/db1v2/pairs/8.53_0575f7270f.db1')); db.segment()
pts = db.find_points(fixed=(41, 17)); cs = db.find_csys(only=(61, 9))
for f, key in ((33, 'after'), (37, 'seq')):
    lay = dict(lay0); lay.update(pts=0, csys=f, csys_key=key)
    db._member_run = db.bystride[73]
    M = [m for m in members(db, pts, cs, lay) if m['prof']]
    st = collections.Counter(); used = np.zeros(len(T), bool)
    for m in M:
        d = np.minimum(np.linalg.norm(A - m['O'], axis=1) + np.linalg.norm(B - m['E'], axis=1), np.linalg.norm(B - m['O'], axis=1) + np.linalg.norm(A - m['E'], axis=1))
        d[used] = 1e18; j = int(np.argmin(d))
        if d[j] < 3:
            used[j] = True; st['match'] += 1
            st['y_ok' if abs(m['y'] @ T[j]['R'][:, 1]) > 0.999 else 'y_bad'] += 1
    hz = [m for m in M if abs(m['x'][2]) < 0.1 and m['L'] > 500]
    print('csys field', f, key, 'members', len(M), dict(st), 'web-vertical', round(sum(1 for m in hz if abs(m['y'][2]) > 0.996) / max(1, len(hz)), 3))
