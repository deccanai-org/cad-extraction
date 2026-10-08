import sys, gzip, numpy as np
sys.path.insert(0, 'kit')
import db1old
data = open(sys.argv[1], 'rb').read()
if data[:2] == b'\x1f\x8b': data = gzip.decompress(data)
o = db1old.Old(data); N = len(o.I_all) - 400; I = o.I_all
av = np.zeros(N, bool); M = N - 380
av[:M] = (I[:M] > 0) & (I[4:M + 4] >= 0) & (I[4:M + 4] <= 100) & (I[72:M + 72] >= 0) & (I[72:M + 72] <= 64)
pr = o.u8[124:124 + M]; av[:M] &= (pr >= 32) & (pr <= 126)
at_off = o.runs(av, 373)
want = sys.argv[2:]
shown = set()
for q in at_off:
    q = int(q)
    if int(I[q + 4]) != 10: continue
    prof = o.cstr(q + 124, 62)
    key = prof.split('/')[0] + '/' + '/'.join(prof.split('/')[1:4])
    if key in shown: continue
    if want and not any(w in prof for w in want): continue
    shown.add(key)
    rec = data[q - 1:q + 373]
    print('====', q, repr(prof), repr(o.cstr(q + 270, 22)))
    for k in range(0, 374, 32):
        chunk = rec[k:k + 32]
        print('%4d' % (k - 1), chunk.hex(' ', 4), ''.join(chr(c) if 32 <= c < 127 else '.' for c in chunk))
    if len(shown) >= 4: break
