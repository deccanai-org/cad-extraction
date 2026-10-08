"""DB1 bolt standard string -> Tekla IFC 'Bolt standard' (verified per GUID-joined group on truth pairs)
   std_alias.py OUT.json DB1 IFC [DB1 IFC ...]"""
import sys, json, collections
sys.path.insert(0, 're'); sys.path.insert(0, '.')
import ifcopenshell, ifcopenshell.util.element as ue
from cache import get
from guid2 import guid_keys
from db1bolts2 import BoltDecoder
outp = sys.argv[1]; args = sys.argv[2:]
alias = collections.defaultdict(collections.Counter)
for i in range(0, len(args), 2):
    db1, ifc = args[i], args[i + 1]
    db, pts, cs, lay, M = get(db1)
    G = {g['seq']: g for g in BoltDecoder(db, pts, cs, lay).decode(M)}
    GK, _, _ = guid_keys(db)
    f = ifcopenshell.open(ifc)
    for e in f.by_type('IfcMechanicalFastener'):
        g = G.get(GK.get((e.Tag or '')[2:38].upper()))
        if g is None: continue
        ps = {}
        for k, v in ue.get_psets(e).items():
            if 'Bolt' in k or 'Fastener' in k: ps.update(v)
        alias[g.get('standard') or '?'][(ps.get('Bolt standard') or '?')] += 1
    print(db1.split('/')[-1], 'done', flush=True)
out = {k: dict(v) for k, v in alias.items()}
json.dump(out, open(outp, 'w'), indent=1); print(json.dumps(out, indent=1))
