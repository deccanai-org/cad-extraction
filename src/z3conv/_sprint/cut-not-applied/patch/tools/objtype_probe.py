"""objtype_probe.py KITDIR DB1... : decoded parts by (attr obj_type, material ANTIMATERIAL?, role in type-11 relations) + top profiles"""
import sys, os, re, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old, db1prof
from db1dec import load
for f in sys.argv[2:]:
    data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    if eng >= 7.5: continue
    M, info, cut_rel = db1old.read(data, eng)
    T = db1old.LAST; attrs = T['attrs']
    kids = {c for v in cut_rel.values() for c in v}; pars = set(cut_rel)
    c = collections.Counter(); profs = collections.defaultdict(collections.Counter)
    for m in M:
        a = attrs.get(m['attr'], {})
        role = 'child' if m['pid'] in kids else ('parent' if m['pid'] in pars else '-')
        k = (a.get('obj_type'), 'ANTI' if m['cut'] else (a.get('mat') or '')[:10], role)
        c[k] += 1; profs[k][(a.get('ben') or '')[:12] + ' ' + (m['prof'] or '')[:14]] += 1
    print('==', os.path.basename(f)[:16], eng, 'parts', len(M))
    for k, v in sorted(c.items(), key=lambda kv: -kv[1]):
        print('   ', v, k, profs[k].most_common(4))
