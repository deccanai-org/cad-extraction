"""For type-11 relation parents that are not decoded parts: find their raw records and say which part-record check fails."""
import sys, os, re, json, struct, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old
from db1dec import load
for f in sys.argv[2:]:
    data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info, cut_rel = db1old.read(data, eng)
    pids = {m['pid'] for m in M}
    P = db1old.PART_NEW if eng >= 7.1 else db1old.PART_OLD
    o = db1old.Old(data); I, D = o.I_all, o.D_all
    miss = sorted({p for p in cut_rel if p not in pids})
    # tables needed to judge a candidate part record
    _, _, _ = None, None, None
    # rebuild the attr / point / csys id sets exactly like db1old.read
    N = len(I) - 400
    import types
    src = open(os.path.join(KIT, 'db1old.py')).read()
    print('==', os.path.basename(f)[:16], eng, 'relation parents not decoded:', len(miss))
    for p in miss[:40]:
        pat = struct.pack('<i', p); q = data.find(pat); hits = []
        while q >= 0:
            if q >= 1 and data[q - 1] in (4, 0, 1, 2, 3, 5, 6, 8, 12, 64, 65, 66, 67):
                ln = D[q + P['csys'] + 24] if q + P['csys'] + 32 < len(D) else float('nan')
                hits.append((q, data[q - 1], int(I[q + P['attr']]), round(float(ln), 1) if np.isfinite(ln) else None))
            q = data.find(pat, q + 1)
        print('  parent', p, 'children', cut_rel[p], 'raw hits (off,prefix,attr@4,len)', hits[:6])
