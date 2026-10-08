"""child_rec.py KITDIR DB1 : type-11 relation children that are not decoded parts -> their own record (id at offset 0, live prefix 4):
print the record layout (ints / doubles), the stride (gaps between such records), and the ids it references (points? parts?)."""
import sys, os, re, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old, db1prof
from db1dec import load
np.set_printoptions(suppress=True, linewidth=250)
f = sys.argv[2]
data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng)
byp = {m['pid']: m for m in M}
o = db1old.Old(data); I = o.I_all; D = o.D_all; N = len(I) - 400
# point table (as db1old)
pv = np.zeros(N, bool); pv[:N - 32] = (I[:N - 32] > 0) & (I[4:N - 28] >= 0) & (I[4:N - 28] <= 64)
for k in (8, 16, 24):
    v = D[k:N - 32 + k]; pv[:N - 32] &= np.isfinite(v) & (np.abs(v) < 1e8)
pts = {}
for q in o.runs(pv, 33):
    q = int(q); pts.setdefault(int(I[q]), np.array([D[q + 8], D[q + 16], D[q + 24]]))
kids = sorted({c for v in cut_rel.values() for c in v if c not in byp})
par_of = {c: p for p, cs in cut_rel.items() for c in cs}
rels = []
recs = []
for c in kids:
    occ = [int(q) for q in np.nonzero(I[8:N] == c)[0] + 8]
    st = [q for q in occ if data[q - 1] == 4 and int(I[q - 8]) != 11]
    recs.append((c, st))
starts = sorted(q for c, st in recs for q in st)
print('==', os.path.basename(f)[:16], eng, 'children not decoded', len(kids), 'with a live record (prefix 4, id at 0):', sum(1 for c, st in recs if st))
print('gaps between those records', collections.Counter(np.diff(starts).tolist()).most_common(8))
sig = collections.Counter()
for c, st in recs[:40]:
    for q in st[:2]:
        ints = [int(I[q + 4 * k]) for k in range(16)]
        refs = ['pt' if v in pts else ('part' if v in byp else '') for v in ints]
        print(' child', c, 'parent', par_of[c], byp[par_of[c]]['prof'] if par_of[c] in byp else None, '@', q, 'ints', ints)
        print('      refs', refs)
        print('      dbl@+4k', [round(float(D[q + k]), 3) for k in range(16, 120, 8)])
        for k, v in enumerate(ints):
            if v in pts: print('      point', v, '@+%d' % (4 * k), np.round(pts[v], 2).tolist())
        sig[tuple(r for r in refs)] += 1
print('ref signatures', sig.most_common(5))
