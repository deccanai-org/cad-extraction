"""part_rels.py KITDIR DB1 PROFILE LENGTH : every relation record (stride 17 / 61, any type) naming the parts of PROFILE with reference
length LENGTH, and the live records of the related objects (ints + doubles) - looking for fittings / line cuts"""
import sys, os, re, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old
from db1dec import load
np.set_printoptions(suppress=True, precision=3, linewidth=250)
data = load(sys.argv[2]); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng); byp = {m['pid']: m for m in M}
o = db1old.Old(data); I = o.I_all; D = o.D_all; N = len(I) - 400
rv = np.zeros(N, bool); Mr = N - 20
rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
rels = collections.defaultdict(list)
for rs in (17, 61):
    for q in o.runs(rv, rs):
        t, a, b = int(I[q + 4]), int(I[q + 8]), int(I[q + 12])
        rels[a].append((t, 'parent', b, q)); rels[b].append((t, 'child', a, q))
sel = [m for m in M if m['prof'] == sys.argv[3] and abs(m['L'] - float(sys.argv[4])) < 1.0]
for m in sel[:3]:
    print('== part', m['pid'], m['prof'], 'L', round(m['L'], 1), 'O', np.round(m['O'], 1), 'x', np.round(m['x'], 3), 'y', np.round(m['y'], 3))
    for t, role, other, q in rels.get(m['pid'], []):
        ob = byp.get(other)
        print('   rel type', t, 'as', role, 'other', other, (ob['prof'], ob['mat'], ob.get('obj_type')) if ob else 'not a part')
        if ob: continue
        for r in [int(x) for x in np.nonzero(I[8:N] == other)[0] + 8 if data[int(x) - 1] == 4][:4]:
            ints = [int(I[r + 4 * k]) for k in range(0, 14)]
            dbl = [round(float(D[r + 8 * k + s]), 4) for s in (0,) for k in range(1, 10)]
            dbl4 = [round(float(D[r + 4 + 8 * k]), 4) for k in range(0, 9)]
            print('       rec @%d ints %s' % (r, ints))
            print('            dbl@+8.. %s' % dbl, 'dbl@+4.. %s' % dbl4)
