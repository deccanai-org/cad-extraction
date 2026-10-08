"""8.85 / 9.08 split bolt-group storage: for GUID-joined fasteners dump every record keyed by the group key and the targets of
their int fields; test hypotheses for frame (stride 49), header (33/66) -> attr, pattern."""
import sys, os, numpy as np, collections, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, '/work/agentwork/db1v2-val/code')
from cache import get
from guid2 import guid_keys
import ifcbolts
db1, ifc = sys.argv[1:3]; N = int(sys.argv[3]) if len(sys.argv) > 3 else 3
db, pts, cs, lay, M = get(db1)
G, back, top = guid_keys(db)
B, GR = ifcbolts.bolts(ifc, True)
def recs_of(k):
    out = []
    for s, (K, O) in db.seqidx.items():
        lo, hi = np.searchsorted(K, k, 'left'), np.searchsorted(K, k, 'right')
        for o in O[lo:hi]: out.append((int(s), int(o)))
    return sorted(out)
def show(o, s, ind='   '):
    ints = [(j, int(x)) for j, x in zip(range(9, s - 3, 4), db.I(o + np.arange(9, s - 3, 4)))]
    dbl = [(j, round(float(x), 4)) for j, x in zip(range(9, s - 7), db.D(o + np.arange(9, s - 7))) if np.isfinite(x) and 1e-3 < abs(x) < 1e7 and abs(x * 1000 - round(x * 1000)) < 1e-4]
    flt = [(j, round(float(x), 3)) for j, x in zip(range(9, s - 3), db.F(o + np.arange(9, s - 3))) if np.isfinite(x) and 1e-2 < abs(x) < 1e6 and abs(x * 100 - round(x * 100)) < 1e-3]
    strs = [(m.start(), m.group().decode('latin1')) for m in re.finditer(rb'[\x20-\x7e]{4,}', db.b[o:o + s])]
    print(f'{ind}stride {s} off {o} ints {ints[:24]}')
    if dbl: print(f'{ind}   dbl {dbl[:16]}')
    if flt: print(f'{ind}   flt {flt[:24]}')
    if strs: print(f'{ind}   strs {strs[:8]}')
n = 0
for g in GR:
    k = G.get(g['guid'])
    if k is None or not g['bolts']: continue
    n += 1
    if n > N: break
    print('\n=== GUID', g['guid'], 'key', k, 'nb', len(g['bolts']), 'd', round(g['d'], 2), 'L', round(g['L'], 2), {kk: v for kk, v in g['pset'].items() if kk in ('Bolt hole diameter', 'Slotted hole x', 'Slotted hole y', 'Washer count', 'Nut count', 'Bolt standard')})
    b0 = g['bolts'][0]; print('   truth bolt0 start', np.round(b0['start'], 2), 'axis', np.round(b0['axis'], 4), 'all starts', [list(np.round(b['start'], 1)) for b in g['bolts'][:4]])
    R = recs_of(k)
    for s, o in R:
        show(o, s)
        if s in (17, 21, 64): continue
        for j, v in [(j, int(x)) for j, x in zip(range(13, s - 3, 4), db.I(o + np.arange(13, s - 3, 4)))]:
            if v > 1000 and v != k:
                for s2, o2 in recs_of(v)[:3]:
                    print(f'      field @{j} -> key {v}:'); show(o2, s2, ind='         ')
