"""quick NML diagnosis: segment + fixed-layout pieces with the old and the new csys gate; members without profiles"""
import sys, json, time, collections, numpy as np, re, os
sys.path.insert(0, 'src')
import db1dec; from db1dec import *
L = json.load(open('src/layouts.json'))
def run(f, eng):
    t = time.time(); data = load(f); db = Db(data); db.segment(); db.PLAUS_MAX = float(os.environ.get("PMAX", "1e8"))
    cand = (L.get(eng) or L['8.85'])['layout']
    pts = db.find_points(fixed=(cand['pts_stride'], cand['pts_k']))
    out = dict(file=os.path.basename(f), mb=round(len(data) / 1e6), n73=len(db.bystride.get(73, [])), n61=len(db.bystride.get(61, [])), pts=len(pts[0]['keys']) if pts else 0)
    # old gate
    recs61 = db.bystride.get(61)
    if recs61 is not None and len(recs61):
        for s, r in db.runs:
            if s == 61 and len(r) >= 3:
                smp = r[:48]
                v1 = np.stack([db.D(smp + 9 + 8 * i) for i in range(3)], 1); v2 = np.stack([db.D(smp + 33 + 8 * i) for i in range(3)], 1)
                out.setdefault('runs61', []).append((len(r), round(float(Db._orthonormal(v1, v2).mean()), 2)))
    cs = db.find_csys(only=(cand['csys_stride'], cand['csys_k']))
    out['csys_new'] = [len(c['keys']) for c in cs]
    if pts and cs:
        lay = dict(cand); lay['pts'] = 0; lay['attr'] = None
        M = members(db, pts, cs, lay); out['members_noattr'] = len(M); out['axis'] = db1dec._axis_agreement(db, pts, lay, M)
    flags = collections.Counter(int(x) for x in np.frombuffer(data, np.uint8)[np.array(db.bystride.get(73, np.zeros(0, np.int64)), np.int64) + 8][:0])
    out['sec'] = round(time.time() - t, 1)
    return out
if __name__ == '__main__':
    for f in sys.argv[2:]: print(json.dumps(run(f, sys.argv[1])), flush=True)
