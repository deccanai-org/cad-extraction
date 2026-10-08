"""lage_probe.py KITDIR DB1... : part_attr ylage@44 / zlage@60 (position in plane / depth) and neighbouring fields, by part kind"""
import sys, os, re, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old
from db1dec import load
for f in sys.argv[2:]:
    data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info, cut_rel = db1old.read(data, eng)
    o = db1old.Old(data); I = o.I_all; D = o.D_all
    # attr record offsets: live copies by id
    av_ids = {m['attr'] for m in M}
    pos = {}
    for a in av_ids:
        for q in [int(x) for x in np.nonzero(I[8:len(I) - 400] == a)[0] + 8]:
            if data[q - 1] == 4 and 0 <= int(I[q + 4]) <= 100 and 0 <= int(I[q + 72]) <= 64 and 32 <= data[q + 124] <= 126:
                pos[a] = q
    c = collections.Counter(); ex = collections.defaultdict(list)
    for m in M:
        q = pos.get(m['attr'])
        if q is None: continue
        kind = ('cut-' if m['cut'] else '') + ('contour' if m.get('old_poly') else 'profile')
        k = (kind, int(I[q + 44]), int(I[q + 60]))
        c[k] += 1
        if len(ex[k]) < 2: ex[k].append((m['prof'], [int(I[q + j]) for j in range(40, 72, 4)], [round(float(D[q + j]), 2) for j in (48, 52, 56, 64, 68)]))
    print('==', os.path.basename(f)[:16], eng)
    for k, v in sorted(c.items(), key=lambda kv: -kv[1])[:14]: print('   ', v, k, ex[k][:1])
