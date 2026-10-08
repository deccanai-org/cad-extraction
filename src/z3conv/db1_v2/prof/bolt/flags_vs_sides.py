import sys, json, collections
sys.path.insert(0, '/Users/dhiren/Downloads/Deccan/z3conv/db1_v2/re')
from bolt853 import setup
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M, seqs, pairs = setup(db1, ifc)
side = json.load(open(ifc + '.washer_sides.json'))
c = collections.Counter()
for g, m in pairs:
    rr = db.attr_records(lay, m['attr'])
    if not rr: continue
    fl = int(db.I([rr[0] + 301])[0]); s = side.get(g['guid'])
    if s is None: continue
    c[(f'{fl:06d}', tuple(s))] += 1
for k, v in sorted(c.items(), key=lambda x: -x[1]): print(v, 'flags', k[0], '-> IFC washers (head side, nut side), nuts', k[1])
