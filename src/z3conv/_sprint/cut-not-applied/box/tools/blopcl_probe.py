"""blopcl_probe.py KITDIR DB1 : new engines - parts whose attribute record names the Boolean operative class (BlOpCl) or CUTPART but
whose material is not ANTIMATERIAL (written as steel today?), and whether the cut-relation table links them"""
import sys, os, re, json, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1dec
data = db1dec.load(sys.argv[2]); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
L = json.load(open(os.path.join(KIT, 'layouts.json')))
lay = (L.get('%.2f' % eng) or {}).get('layout'); var = [v['layout'] for v in L.values() if v.get('layout')]
db, pts, cs, lay = db1dec.decode(data, lay, var, True)
M = db1dec.members(db, pts, cs, lay)
links = db.find_cut_links(M)
c = collections.Counter(); ex = collections.defaultdict(list)
for m in M:
    rr = db.attr_records(lay, m['attr']) if m.get('attr') else []
    raw = db.b[rr[0]:rr[0] + lay['attr_stride']] if rr else b''
    k = ('BlOpCl' if b'BlOpCl' in raw else '-', 'CUTPART' if b'CUTPART' in raw else '-', 'cut' if m.get('cut') else 'steel')
    c[k] += 1
    if len(ex[k]) < 4: ex[k].append((m['seq'], m['prof'], round(m['L'], 1)))
print('==', os.path.basename(sys.argv[2])[:16], eng, 'members', len(M), 'cut_layout', db.cut_layout)
for k, v in c.most_common(): print('   ', v, k, ex[k])
