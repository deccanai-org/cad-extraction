"""occ_dump.py KITDIR DB1 PID... : every raw occurrence of the int32 PID with the bytes around it (records naming the part that are not
its own part record / relation records): candidates for fittings / line cuts stored with a part reference"""
import sys, os, re, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old
from db1dec import load
data = load(sys.argv[2])
o = db1old.Old(data); I = o.I_all; D = o.D_all; N = len(I) - 400
for pid in map(int, sys.argv[3:]):
    occ = [int(q) for q in np.nonzero(I[16:N] == pid)[0] + 16]
    print('== pid', pid, 'occurrences', len(occ))
    for q in occ:
        # find the record start: nearest preceding prefix byte 4 within 400 bytes where an id-like int follows
        ctx_i = [int(I[q + k]) for k in range(-16, 32, 4)]
        dd = []
        for s in range(-24, 72, 8):
            v = float(D[q + s])
            dd.append(round(v, 3) if np.isfinite(v) and abs(v) < 1e7 and (v == 0 or abs(v) > 1e-6) else None)
        print('   @%d pre(q-1)=%d ints[-16..+28] %s | dbl[-24..+64] %s' % (q, data[q - 1], ctx_i, dd))
