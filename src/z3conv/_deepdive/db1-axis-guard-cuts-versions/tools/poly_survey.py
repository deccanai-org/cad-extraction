"""Polygon table survey (old engines): records per (id, no), prefix bytes, and how many PARTS get a different outline when the
live copy (prefix byte 4, not all-zero) is preferred over stray copies."""
import sys, os, re, collections, numpy as np
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(H, '..', 'kit_snapshot'))
import db1old
from db1dec import load
for f in sys.argv[1:]:
    data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    if eng >= 7.5: continue
    o = db1old.Old(data); I = o.I_all; F = o.F_all; N = len(I) - 400
    P = db1old.PART_NEW if eng >= 7.1 else db1old.PART_OLD
    gv = np.zeros(N, bool); Mx = N - 340
    gv[:Mx] = (I[:Mx] > 0) & (I[4:Mx + 4] >= 0) & (I[4:Mx + 4] <= 64)
    for k in range(12, 132, 4):
        v = F[k:Mx + k]; gv[:Mx] &= np.isfinite(v) & (np.abs(v) < 1e7)
    pg_off = [int(q) for q in o.runs(gv, 333)]
    rec = collections.defaultdict(list)
    for q in pg_off:
        pts10 = [(float(F[q + 12 + 4 * i]), float(F[q + 52 + 4 * i]), float(F[q + 92 + 4 * i])) for i in range(10)]
        rec[(int(I[q]), int(I[q + 4]))].append((q, data[q - 1], pts10))
    pre = collections.Counter(r[1] for v in rec.values() for r in v)
    conflict = {k: v for k, v in rec.items() if len({tuple(r[2]) for r in v}) > 1}
    bygid = collections.defaultdict(list)
    for k in rec: bygid[k[0]].append(k)
    live_multi = sum(1 for v in conflict.values() if sum(1 for r in v if r[1] == 4) > 1)
    nolive = sum(1 for v in conflict.values() if not any(r[1] == 4 for r in v))
    M, info, cut_rel = db1old.read(data, eng)
    def outline(gid, npts, prefer):
        nos = sorted({k[1] for k in bygid[gid]})
        raw = []
        if not prefer:  # == db1old today
            lst = []
            for k in bygid[gid]:
                for r in rec[k]: lst.append((k[1], r[2]))
            for no, p10 in sorted(lst):
                for p in p10:
                    if len(raw) < npts: raw.append(p)
            return raw
        for no in nos:
            cands = rec[(gid, no)]
            live = [r for r in cands if r[1] == 4 and any(any(c != 0 for c in p) for p in r[2])]
            pick = live[-1] if live else sorted(cands, key=lambda r: r[2])[0]
            for p in pick[2]:
                if len(raw) < npts: raw.append(p)
        return raw
    diff = []; zero_before = zero_after = 0; n = 0
    for m in M:
        if not m.get('old_poly'): continue
        n += 1
        gid = int(I[m['off'] + P['poly']]); npts = len(m['old_poly'])
        a = outline(gid, npts, False); b = outline(gid, npts, True)
        assert [tuple(x) for x in a] == [tuple(x) for x in m['old_poly']], 'replica mismatch'
        za = all(all(c == 0 for c in p) for p in a); zb = all(all(c == 0 for c in p) for p in b)
        zero_before += za; zero_after += zb
        if a != b: diff.append((m['pid'], m['prof'], m['mat'], 'cut' if m['cut'] else ('bolt' if m['bolt'] else 'part'), 'zero->real' if za and not zb else 'changed'))
    print('==', os.path.basename(f)[:12], eng, 'poly recs', len(pg_off), 'prefix', pre.most_common(4), '| conflicting (id,no)', len(conflict),
          'with >1 live copy', live_multi, 'without live copy', nolive, '| parts with outline', n, 'all-zero outline before', zero_before, 'after', zero_after,
          '| parts whose outline changes', len(diff), collections.Counter(d[3] + ':' + d[4] for d in diff).most_common())
    for d in diff[:6]: print('     ', d)
