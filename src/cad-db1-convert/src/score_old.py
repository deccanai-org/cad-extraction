import sys, os, json, pickle, collections, glob, concurrent.futures as cf, numpy as np
sys.path.insert(0, '/opt/db1v2/src3')
def one(tag):
    import db1old
    from db1dec import load
    T = pickle.load(open(f'/opt/db1v2/pairs/{tag}.ifc.truth.pkl', 'rb'))
    data = load(f'/opt/db1v2/pairs/{tag}.db1'); import re
    eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info = db1old.read(data, eng)
    A = np.array([t['a'] for t in T]) if T else np.zeros((0, 3)); B = np.array([t['b'] for t in T]) if T else np.zeros((0, 3))
    used = np.zeros(len(T), bool); st = collections.Counter(); bad = collections.Counter()
    for m in M:
        if not len(T) or m['cut']: continue
        d = np.minimum(np.linalg.norm(A - m['O'], axis=1) + np.linalg.norm(B - m['E'], axis=1), np.linalg.norm(B - m['O'], axis=1) + np.linalg.norm(A - m['E'], axis=1))
        d[used] = 1e18; j = int(np.argmin(d))
        if d[j] < 3:
            used[j] = True; st['match'] += 1
            st['prof_ok' if m['prof'] == T[j]['prof'] else 'prof_diff'] += 1
            if m['prof'] != T[j]['prof']: bad[(m['prof'], T[j]['prof'])] += 1
            R = T[j]['R']; st['frame_ok' if abs(-m['xr'] @ R[:, 2] - 1) < 1e-4 and abs(np.cross(m['xr'], m['y']) @ R[:, 0] - 1) < 1e-4 else 'frame_bad'] += 1
    return tag, eng, info, dict(st), bad.most_common(4), len(T)
tags = sorted({os.path.basename(p)[:-4] for p in glob.glob('/opt/db1v2/pairs/6.87_*.db1') + glob.glob('/opt/db1v2/pairs/7.24_*.db1')})
with cf.ProcessPoolExecutor(len(tags)) as ex:
    for f in cf.as_completed([ex.submit(one, t) for t in tags]): print(*f.result(), flush=True)
