import os, pickle, hashlib, json, sys
def get(path, eng, src='src'):
    sys.path.insert(0, src)
    import db1dec
    from db1dec import Db, decode, members, load
    L = json.load(open(os.path.join(src, 'layouts.json'))); VA = [v['layout'] for v in L.values() if v.get('layout')]
    h = hashlib.md5((os.path.abspath(path) + str(os.path.getsize(path)) + str(os.path.getmtime(os.path.join(src, 'db1dec.py')))).encode()).hexdigest()[:16]
    os.makedirs('_cache', exist_ok=True); cp = os.path.join('_cache', h + '.pkl')
    data = load(path)
    if os.path.exists(cp):
        st, lay, M, pts, cs = pickle.load(open(cp, 'rb'))
        db = Db(data); db.__dict__.update(st); return data, db, pts, cs, lay, M
    db, pts, cs, lay = decode(data, (L.get(eng) or {}).get('layout'), VA, len(data) < 20_000_000)
    M = members(db, pts, cs, lay) if lay and lay.get('csys') is not None else []
    st = {k: v for k, v in db.__dict__.items() if k not in ('b', 'u8', 'L')}
    pickle.dump((st, lay, M, pts, cs), open(cp, 'wb'), protocol=4)
    return data, db, pts, cs, lay, M
