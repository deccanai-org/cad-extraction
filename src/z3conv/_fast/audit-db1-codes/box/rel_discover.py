"""rel_discover.py ID [ID..]: 7.1-7.4x engines find no stride-17 relation records (cut_relations = 0 -> every Tekla cut dropped).
Locate where cut parts (ANTIMATERIAL) are referenced: every int32 occurrence of a cut part id, the nearest normal-part id before /
after it, the type-like ints around, spacing of consecutive hits (stride), and geometric validation (cut bbox meets parent bbox)."""
import sys, os, json, collections
import numpy as np
W = os.path.dirname(os.path.abspath(__file__)); os.chdir(W)
sys.path.insert(0, os.path.join(W, 'kits', 'i'))
import db1old
from db1dec import load
for a in sys.argv[1:]:
    i = [f[:-4] for f in os.listdir('src') if f.startswith(a)][0]
    data = load(f'src/{i}.db1'); eng = float(data[:16].decode('latin-1', 'replace').split()[0].split('_')[-1]) if False else None
    import re
    eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info, cut_rel = db1old.read(data, eng)
    cuts = {m['pid']: m for m in M if m.get('cut')}; parts = {m['pid']: m for m in M if not m.get('cut') and not m.get('bolt')}
    bolts = {m['pid']: m for m in M if m.get('bolt')}
    o = db1old.Old(data); I = o.I_all
    print('==', i[:12], 'engine', eng, 'members', len(M), 'cuts', len(cuts), 'parts', len(parts), 'bolts', len(bolts), info)
    C = np.array(sorted(cuts), np.int64)
    pos = np.nonzero(np.isin(I, C))[0]
    print('int32 occurrences of cut ids:', len(pos))
    P = np.array(sorted(parts), np.int64)
    isP = np.isin(I, P)
    deltas = collections.Counter(); ctx = collections.Counter()
    hits = []
    for q in pos:
        q = int(q)
        for d in (-16, -12, -8, -4, 4, 8, 12, 16):
            if 0 <= q + d < len(I) and isP[q + d]:
                deltas[d] += 1
                hits.append((q, d))
    print('normal-part id at offset from the cut id:', deltas.most_common(8))
    if not deltas:
        continue
    dbest = deltas.most_common(1)[0][0]
    hq = sorted(q for q, d in hits if d == dbest)
    gaps = collections.Counter(np.diff(hq).tolist())
    print('spacing of hits (best offset):', gaps.most_common(8))
    # what sits around: ints at offsets -12..+12 relative to the cut id (type field candidates)
    for k in (-12, -8, -4, 4, 8):
        vals = collections.Counter(int(I[q + k]) for q in hq if 0 <= q + k < len(I))
        print(f'  ints at {k:+d}:', vals.most_common(6))
    # geometric check: parent part bbox vs cut part bbox (from O, x, L and a 1 m pad)
    def box(m):
        O = np.asarray(m['O']); E = O + np.asarray(m['x']) * m['L']
        pts = np.array([O, E] + ([O + np.asarray(m['xr']) * q[0] + np.asarray(m['y']) * q[1] for q in (m.get('old_poly') or [])]))
        return pts.min(0), pts.max(0)
    ok = tot = 0
    for q in hq[:3000]:
        c = int(I[q]); p = int(I[q + dbest])
        if c in cuts and p in parts:
            a0, a1 = box(cuts[c]); b0, b1 = box(parts[p]); tot += 1
            ok += bool(np.all(a1 >= b0 - 300) and np.all(b1 >= a0 - 300))
    print('pairs geometrically overlapping (300 mm pad):', ok, '/', tot)
