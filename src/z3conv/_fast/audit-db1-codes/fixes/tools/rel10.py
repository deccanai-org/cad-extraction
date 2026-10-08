"""rel10.py: Tekla relation table (old engines, stride-17 records id@0 type@4 id1@8 id2@12) of every 6.87/7.01/7.24 model ->
rel/<id>.json {types: {type: n}, pairs: {type: [[id1, id2], ...]} for the types that touch bolt groups or parts}"""
import json, os, sys, collections, concurrent.futures as cf
import numpy as np
W = os.path.dirname(os.path.abspath(__file__)); os.chdir(W)
sys.path.insert(0, os.path.join(W, 'kits', 'i'))
import re, zlib
def _eng(path):
    raw = open(path, 'rb').read(1 << 16)
    data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
    m = re.search(rb'(\d+\.\d+)', data[:16])
    return m.group(1).decode() if m else None
ENG = {f[:-4]: _eng('src/' + f) for f in os.listdir('src') if f.endswith('.db1')}
os.makedirs('rel', exist_ok=True)


def one(i):
    out = f'rel/{i}.json'
    if os.path.exists(out):
        return i, 'cached'
    import db1old
    from db1dec import load
    data = load(f'src/{i}.db1')
    o = db1old.Old(data); N = len(o.I_all) - 400; I = o.I_all
    rv = np.zeros(N, bool); Mr = N - 20
    rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
    off = o.runs(rv, 17)
    ty = collections.Counter(); pairs = collections.defaultdict(list)
    for q in off:
        t = int(I[q + 4]); ty[t] += 1
        pairs[t].append([int(I[q + 8]), int(I[q + 12]), int(I[q])])
    json.dump({'types': dict(ty), 'pairs': {str(t): v for t, v in pairs.items()}}, open(out, 'w'))
    return i, len(off)


ids = [i for i, e in ENG.items() if e in ('6.87', '7.01', '7.24')]
with cf.ProcessPoolExecutor(6) as ex:
    for r in ex.map(one, ids):
        print(*r, flush=True)
