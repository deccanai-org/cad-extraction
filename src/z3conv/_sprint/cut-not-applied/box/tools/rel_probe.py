"""rel_probe.py KITDIR DB1... : old engines - where do cut-part ids occur outside their own part record, and which
neighbouring int32 (relative byte offset d) holds a decoded non-cut part id?  -> the part-cut relation layout per engine.
Tekla object ids are unique across tables, so a part id next to a cut id at a fixed offset over most cuts is a link."""
import sys, os, re, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old, db1prof
from db1dec import load
for f in sys.argv[2:]:
    data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    if eng >= 7.5: continue
    M, info, cut_rel = db1old.read(data, eng)
    M = [m for m in M if not db1prof.is_null_record(m)]
    cuts = [m for m in M if m['cut']]
    parts = {m['pid'] for m in M if not m['cut'] and not m['bolt']}
    own = {m['off'] for m in M}
    o = db1old.Old(data); I = o.I_all; N = len(I) - 80
    hist = collections.Counter(); occ_n = collections.Counter(); per_cut = collections.defaultdict(set); ex = {}
    around = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for m in cuts:
        occ = np.nonzero(I[80:N] == m['pid'])[0] + 80
        occ = [int(q) for q in occ if int(q) not in own]
        occ_n[min(len(occ), 9)] += 1
        for q in occ:
            for d in range(-64, 65):
                if d == 0: continue
                v = int(I[q + d])
                if v in parts:
                    hist[d] += 1; per_cut[d].add(m['pid']); ex.setdefault(d, (q, m['pid'], v))
                    for k in (-12, -8, -4, 4, 8, 12, 16):
                        around[d][k][int(I[q + k])] += 1
                    around[d]['pre'][data[q - 1]] += 1
    print('==', os.path.basename(f)[:16], eng, 'parts', len(M), 'cuts', len(cuts), 'type-11 linked cuts', len({c for v in cut_rel.values() for c in v}),
          'occurrences per cut (outside own record)', sorted(occ_n.items()))
    for d, n in sorted(hist.items(), key=lambda kv: -len(per_cut[kv[0]]))[:6]:
        q, c, p = ex[d]
        print('   d=%+d hits %d distinct cuts %d | e.g. @%d cut %d part %d ints[-16..+20] %s' % (d, n, len(per_cut[d]), q, c, p, [int(I[q + k]) for k in range(-16, 24, 4)]))
        print('        common values at cut-id offsets:', {k: v.most_common(3) for k, v in around[d].items()})
