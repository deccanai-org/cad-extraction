"""missing_refs.py KITDIR DB1 : type-11 relation parents / children that are not decoded parts: find their live part-layout record
(prefix 4, id at 0) and report which reference of db1old.read fails (attr / csys-attr / p1 / p2), plus the raw attr record."""
import sys, os, re, collections, struct, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old
from db1dec import load
f = sys.argv[2]
data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng)
T = db1old.LAST; P = T['P']; attrs, csa, pts = T['attrs'], T['csa'], T['pts']
byp = {m['pid']: m for m in M}
o = db1old.Old(data); I = o.I_all; D = o.D_all; N = len(I) - 400
par_nd = sorted(p for p in cut_rel if p not in byp)
kid_nd = sorted({c for v in cut_rel.values() for c in v if c not in byp})
def attr_raw(a):
    out = []
    for q in [int(x) for x in np.nonzero(I[8:N] == a)[0] + 8]:
        if data[q - 1] != 4: continue
        txt = re.findall(rb'[\x20-\x7e]{2,}', data[q:q + 373])
        out.append((q, int(I[q + 4]), int(I[q + 8]), int(I[q + 72]), [t.decode('latin1')[:30] for t in txt[:6]]))
    return out
stat = collections.Counter()
for tag, ids in (('PARENT', par_nd), ('CHILD', kid_nd)):
    for i in ids:
        cands = []
        for q in [int(x) for x in np.nonzero(I[8:N] == i)[0] + 8]:
            if data[q - 1] != 4 or q + P['csys'] + 32 >= len(D): continue
            Ln = D[q + P['csys'] + 24]
            if not (np.isfinite(Ln) and 0 <= Ln < 1e6 and I[q + P['attr']] > 0): continue
            a, c_, p1, p2 = int(I[q + P['attr']]), int(I[q + P['csa']]), int(I[q + P['p1']]), int(I[q + P['p2']])
            fail = [n for n, ok in (('attr', a in attrs), ('csa', c_ in csa), ('p1', p1 in pts), ('p2', p2 in pts)) if not ok]
            cands.append((q, a, c_, p1, p2, round(float(Ln), 2), fail))
        key = (tag, 'no part-layout record' if not cands else ('fails:' + ','.join(sorted(set(x for cd in cands for x in cd[6]))) if all(cd[6] for cd in cands) else 'all refs ok (not in a run?)'))
        stat[key] += 1
        if stat[key] <= 4:
            print(tag, i, 'candidates', cands[:2])
            for cd in cands[:1]:
                if 'attr' in cd[6]: print('     attr', cd[1], 'raw records', attr_raw(cd[1])[:3])
                else: print('     attr', cd[1], attrs.get(cd[1]))
print('==', os.path.basename(f)[:16], eng, dict(stat))
