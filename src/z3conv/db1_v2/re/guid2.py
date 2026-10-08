"""GUID join. Tekla stores each object's GUID as a string in a 72-byte record keyed by the object key:
[objid][ref][04][key@+9]...[GUID string @+33, optionally prefixed 'ID'] (7.82 / 8.07 / 8.53 / 8.44 verified).
-> {GUID upper: key}. Falls back to the per-file best back-offset when the structure is not found."""
import re, numpy as np, collections
from db1dec import inkeys
RX = re.compile(rb'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}')
def guid_keys(db, target_keys=None, sample=6000):
    """GUID string -> object key. Candidates per GUID: the 72-byte record rule (key @+9, GUID @+33 after an optional 'ID') and the
    file's best back-offset (8.85 / 9.x keep GUIDs in 64-byte records: key @+9 = @+21, GUID @+25 -> back 4). With target_keys the
    candidate that is a known key wins; else the record rule where its header byte checks, else the back-offset."""
    d = db.b; found = [(m.start(), m.group().decode().upper()) for m in RX.finditer(d)]
    K = np.asarray(target_keys if target_keys is not None else db.gkeys, np.int64)
    Ks = set(int(x) for x in K) if target_keys is not None else None
    best = collections.Counter(); smp = found[:: max(1, len(found) // sample)]
    for back in range(4, 97):
        v = np.array([int.from_bytes(d[g - back:g - back + 4], 'little', signed=True) for g, _ in smp if g >= back])
        best[back] = int(inkeys(np.sort(K), v).sum()) if len(v) else 0
    back = best.most_common(1)[0][0]
    G = {}; c = collections.Counter()
    for g, s in found:
        cands = []
        base = g - 2 if d[g - 2:g] == b'ID' else g
        st = base - 33
        if st >= 0 and d[st + 8] == 4:
            k72 = int.from_bytes(d[st + 9:st + 13], 'little', signed=True)
            if k72 > 0: cands.append(('rec72', k72))
        if g >= back: cands.append(('back', int.from_bytes(d[g - back:g - back + 4], 'little', signed=True)))
        pick = None
        if Ks is not None:
            pick = next((cd for cd in cands if cd[1] in Ks), None)
        if pick is None and cands: pick = cands[0]
        if pick is None: continue
        if s not in G: G[s] = pick[1]; c[pick[0]] += 1
    return G, f'rec72|back{back}', c.most_common()
