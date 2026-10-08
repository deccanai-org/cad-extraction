"""attr_probe.py KITDIR DB1 : part-layout records (prefix 4) whose only failing reference is the attribute record:
find every raw copy of the attr id and show why the stride-373 part_attr scan does not take it."""
import sys, os, re, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old
from db1dec import load
f = sys.argv[2]
data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng)
T = db1old.LAST; P = T['P']; attrs, csa, pts = T['attrs'], T['csa'], T['pts']
byp = {m['pid']: m for m in M}
o = db1old.Old(data); I = o.I_all; D = o.D_all; N = len(I) - 400
s = P['stride']; Mx = N - s - 8
qv = np.zeros(N, bool)
ln = D[P['csys'] + 24:Mx + P['csys'] + 24]
qv[:Mx] = (I[:Mx] > 0) & (I[P['attr']:Mx + P['attr']] > 0) & np.isfinite(ln) & (ln >= 0) & (ln < 1e6)
for k in (0, 8, 16):
    v = D[P['csys'] + k:Mx + P['csys'] + k]; qv[:Mx] &= np.isfinite(v) & (np.abs(v) < 1e8)
cand = [int(q) for q in np.nonzero(qv)[0] if data[int(q) - 1] == 4]
miss = collections.Counter(); ex = collections.defaultdict(list); pids = {m['pid'] for m in M}
for q in cand:
    pid = int(I[q])
    if pid in pids: continue
    a, c_, p1, p2 = int(I[q + P['attr']]), int(I[q + P['csa']]), int(I[q + P['p1']]), int(I[q + P['p2']])
    ok = (c_ in csa, p1 in pts, p2 in pts)
    if all(ok) and a not in attrs:
        miss['only_attr'] += 1; ex['only_attr'].append((q, pid, a))
    elif all(ok) and a in attrs:
        miss['all_ok_but_not_decoded'] += 1; ex['all_ok'].append((q, pid, a))
    else:
        miss['other_fail'] += 1
print('==', os.path.basename(f)[:16], eng, 'live part-layout records not decoded:', dict(miss))
at_n = collections.Counter(a for _, _, a in ex['only_attr'])
print('distinct missing attr ids', len(at_n), at_n.most_common(8))
for a, n in at_n.most_common(12):
    print(' attr', a, 'used by', n, 'part records')
    for q in [int(x) for x in np.nonzero(I[8:N] == a)[0] + 8]:
        b = data[q:q + 373]
        prof = o.cstr(q + 124, 62); mat = o.cstr(q + 270, 22); ben = o.cstr(q + 102, 22)
        print('    @%d prefix %d obj_type %d form %d npoints %d ben %r prof %r mat %r | str %s' % (q, data[q - 1], int(I[q + 4]), int(I[q + 8]), int(I[q + 72]), ben, prof, mat,
              [t.decode('latin1')[:24] for t in re.findall(rb'[\x20-\x7e]{3,}', b)][:6]))
