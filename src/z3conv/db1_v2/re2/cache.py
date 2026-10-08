import os, pickle, json, hashlib
from db1dec import *
L = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'layouts.json'))); VA = [v['layout'] for v in L.values() if v.get('layout')]
CD = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_cache'); os.makedirs(CD, exist_ok=True)

def get(path, eng=None, allow_full=False):
    h = hashlib.md5((os.path.abspath(path) + str(os.path.getsize(path))).encode()).hexdigest()[:16]
    cp = os.path.join(CD, h + '.pkl')
    data = load(path)
    if os.path.exists(cp):
        st, lay, M, pts, cs = pickle.load(open(cp, 'rb'))
        db = Db(data); db.__dict__.update(st); return db, pts, cs, lay, M
    if eng is None:
        import re; eng = re.search(rb'(\d+\.\d+)', data[:16]).group(1).decode()
    base = (L.get(eng) or {}).get('layout')
    db, pts, cs, lay = decode(data, base, VA, allow_full)
    M = members(db, pts, cs, lay) if lay and lay.get('csys') is not None else []
    st = {k: v for k, v in db.__dict__.items() if k not in ('b', 'u8', 'L')}
    pickle.dump((st, lay, M, pts, cs), open(cp, 'wb'), protocol=4)
    return db, pts, cs, lay, M
