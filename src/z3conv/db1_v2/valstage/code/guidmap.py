"""Tekla GUID table in a .db1 (8.x): records [objid][ref][04][key][f13][f17][0][key][key]'XXXXXXXX-XXXX-...'\0.
-> {GUID(upper): key}.  IFC Tag 'ID<guid>' -> element.  Joins IFC elements to DB1 object keys."""
import re, sys, numpy as np, collections
RX = re.compile(rb'[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\x00')

def db1_guids(data):
    out = {}; info = collections.Counter()
    for m in RX.finditer(data):
        g = m.start()
        if g < 33: continue
        k25 = int.from_bytes(data[g-8:g-4], 'little', signed=True); k29 = int.from_bytes(data[g-4:g], 'little', signed=True)
        k9 = int.from_bytes(data[g-24:g-20], 'little', signed=True)
        fl = data[g-25]
        info[(fl, k25 == k29, k9 == k25)] += 1
        out[m.group()[:-1].decode()] = dict(key=k9, k25=k25, k29=k29, f13=int.from_bytes(data[g-20:g-16], 'little', signed=True),
                                            f17=int.from_bytes(data[g-16:g-12], 'little', signed=True), off=g - 33)
    return out, info

def ifc_tags(path):
    import ifcopenshell
    f = ifcopenshell.open(path); out = {}
    for e in f.by_type('IfcProduct'):
        t = getattr(e, 'Tag', None)
        if t and t.startswith('ID') and len(t) >= 38: out[t[2:38].upper()] = e
    return f, out

if __name__ == '__main__':
    from db1dec import load
    d = load(sys.argv[1]); G, info = db1_guids(d); print('db1 guids', len(G), info.most_common(6))
    f, T = ifc_tags(sys.argv[2]); print('ifc tagged', len(T), collections.Counter(e.is_a() for e in T.values()).most_common(8))
    hit = collections.Counter(T[g].is_a() for g in T if g in G); print('joined', sum(hit.values()), hit.most_common(8))
