"""Generalised Tekla GUID table reader: GUID strings (upper or lower case, NUL-terminated) in the DB1;
the object key is the int at a per-file offset before the string, found as the offset whose ints best
hit a given key set (member seqs)."""
import re, numpy as np, collections
RX = re.compile(rb'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?=\x00)')
def scan(data):
    return [(m.start(), m.group().decode().upper()) for m in RX.finditer(data)]
def best_offset(data, G, keys, cands=range(4, 80, 1)):
    keys = np.asarray(sorted(keys), np.int64); u8 = np.frombuffer(data, np.uint8)
    pos = np.array([g for g, _ in G], np.int64); sc = {}
    for k in cands:
        p = pos - k; p = p[p >= 0]
        v = (u8[p[:, None] + np.arange(4)].copy().view('<i4')[:, 0]).astype(np.int64)
        i = np.searchsorted(keys, v); i[i >= len(keys)] = 0
        sc[k] = int((keys[i] == v).sum())
    k = max(sc, key=sc.get); return k, sc[k], sorted(sc.items(), key=lambda x: -x[1])[:5]
def guid_map(data, keys):
    G = scan(data); k, n, top = best_offset(data, G, keys)
    out = {}
    for g, s in G:
        v = int.from_bytes(data[g - k:g - k + 4], 'little', signed=True)
        out.setdefault(s, v)
    return out, dict(offset=k, hits=n, guids=len(G), top=top)
