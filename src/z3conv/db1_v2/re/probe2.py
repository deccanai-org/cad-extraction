import sys, collections, numpy as np, re
from cache import *
from guidmap import db1_guids, ifc_tags
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
seqs = {m['seq']: m for m in M}
G, info = db1_guids(db.b); f, T = ifc_tags(ifc)
fm = [(g, e, seqs[G[g]['key']]) for g, e in T.items() if e.is_a() == 'IfcMechanicalFastener' and g in G and G[g]['key'] in seqs]
print('fastener members', len(fm))
print('profiles', collections.Counter(m['prof'] for g, e, m in fm).most_common(10))
print('strides', collections.Counter(m['stride'] for g, e, m in fm).most_common(5))
print('member strides overall', collections.Counter(m['stride'] for m in M).most_common(6))
for g, e, m in fm[:4]:
    print(g, e.NominalDiameter, e.NominalLength, 'L', round(m['L'], 2), 'attr', m['attr'], 'O', np.round(m['O'], 1), 'x', np.round(m['x'], 3), 'y', np.round(m['y'], 3))
    rr = db.attr_records(lay, m['attr']) if m['attr'] else []
    for o in rr[:2]:
        print('   attr rec stride', int(db.lookup_stride([m['attr']])[0]), [(mm.start(), mm.group().decode('latin1')) for mm in re.finditer(rb'[\x20-\x7e]{3,}', db.b[o:o + 400])][:12])
    # all records keyed by this seq
    for o in db.lookup_all(m['seq']):
        st = int(db.gstr[np.searchsorted(db.goffs, o)]) if False else None
    ks = [(int(s), int(o)) for s, (K, O) in db.seqidx.items() for o in O[np.searchsorted(K, m['seq'], 'left'):np.searchsorted(K, m['seq'], 'right')]]
    print('   records keyed by seq:', ks)
