"""GUID join. Tekla stores each object's GUID as a string in a 72-byte record keyed by the object key:
[objid][ref][04][key@+9]...[GUID string @+33, optionally prefixed 'ID'] (7.82 / 8.07 / 8.53 / 8.44 verified).
-> {GUID upper: key}. Falls back to the per-file best back-offset when the structure is not found."""
import re, numpy as np, collections
from db1dec import inkeys
RX = re.compile(rb'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}')
def guid_keys(db, target_keys=None, sample=6000):
    d = db.b; G = {}; c = collections.Counter()
    found = [(m.start(), m.group().decode().upper()) for m in RX.finditer(d)]
    for g, s in found:
        base = g - 2 if d[g - 2:g] == b'ID' else g
        st = base - 33
        if st >= 0 and d[st + 8] == 4:
            k = int.from_bytes(d[st + 9:st + 13], 'little', signed=True)
            if k > 0:
                G.setdefault(s, k); c['rec72'] += 1; continue
        c['other'] += 1
    if c['rec72'] >= 0.98 * max(1, len(found)):
        return G, 'rec72', c.most_common()
    G72 = dict(G)
    K = target_keys if target_keys is not None else db.gkeys
    best = collections.Counter(); smp = found[:: max(1, len(found) // sample)]
    for back in range(4, 97):
        v = np.array([int.from_bytes(d[g - back:g - back + 4], 'little', signed=True) for g, _ in smp if g >= back])
        best[back] = int(inkeys(K, v).sum()) if len(v) else 0
    back = best.most_common(1)[0][0]; G = dict(G72)
    for g, s in found:
        if g >= back and s not in G: G[s] = int.from_bytes(d[g - back:g - back + 4], 'little', signed=True)
    return G, ('rec72+%d' % back), best.most_common(4)
