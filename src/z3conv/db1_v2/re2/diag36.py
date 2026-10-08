"""obj_type of bolt-group attribute records for GUID-joined fasteners that were not decoded; dump an obj_type-3 example"""
import sys, os, json, numpy as np, collections, re
sys.path.insert(0, '/work/agentwork/db1v2-val/code')
from cache import get
from guid2 import guid_keys
from db1bolts2 import BoltDecoder, LAYS
import ifcbolts
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
bd = BoltDecoder(db, pts, cs, lay); G = {g['seq']: g for g in bd.decode(M)}
GK, back, _ = guid_keys(db); _, GR = ifcbolts.bolts(ifc, True)
C = bd.C; P = bd.P
why = collections.Counter(); ex = {}
for tb in GR:
    k = GK.get(tb['guid'])
    if k is None or k in G: continue
    best = None
    for o in db.lookup_all(k):
        for L in LAYS:
            a = int(db.I([o + L['attr']])[0]); ao = int(db.lookup([a])[0])
            ob = int(db.I([ao + 13])[0]) if ao >= 0 else None
            X = db.D(o + L['xyz'] + 8 * np.arange(4)); p1 = db._pt(P, db.I([o + L['p1']]))[0]; p2 = db._pt(P, db.I([o + L['p2']]))[0]; cv = int(db.I([o + L['csys']])[0])
            score = (ob is not None) + bool(np.all(np.isfinite(X)) and np.all(np.abs(X[:3]) < 1e8) and X[3] > 0) + bool(np.all(np.isfinite(p1)) and np.all(np.isfinite(p2))) + (cv in C['map'])
            cand = (score, L['name'], ob, int(db.lookup_stride([a])[0]) if ao >= 0 else None, o)
            if best is None or cand[0] > best[0]: best = cand
    if best is None: why['no_records'] += 1; continue
    why[best[:4]] += 1
    if best[2] not in (10,) and best[0] == 4 and best[2] not in ex: ex[best[2]] = (tb, best)
print('best-candidate (score, layout, attr obj_type, attr stride):'); [print('  ', v, k) for k, v in why.most_common(12)]
for ob, (tb, b) in ex.items():
    o = b[4]; a = int(db.I([o + 13])[0]); ao = int(db.lookup([a])[0]); S = int(db.lookup_stride([a])[0])
    print('\nobj_type', ob, 'GUID', tb['guid'], 'nb', len(tb['bolts']), 'd', tb['d'], 'L', tb['L'], {k: v for k, v in tb['pset'].items() if k in ('Bolt standard', 'Bolt hole diameter', 'Washer count', 'Nut count')})
    raw = db.b[ao:ao + S]
    print('  attr stride', S, 'ints', [(j, int(x)) for j, x in zip(range(9, 64, 4), db.I(ao + np.arange(9, 64, 4)))])
    print('  strs', [(m.start(), m.group().decode('latin1')) for m in re.finditer(rb'[\x20-\x7e]{3,}', raw)][:10])
    print('  flt', [(j, round(float(x), 3)) for j, x in zip(range(9, S - 3), db.F(ao + np.arange(9, S - 3))) if np.isfinite(x) and 0.5 < abs(x) < 1e5 and abs(x * 100 - round(x * 100)) < 1e-3][:20])
