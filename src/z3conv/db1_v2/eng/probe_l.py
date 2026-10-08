import sys, collections, numpy as np, re
sys.path.insert(0, 'src')
from db1dec import *
f = sys.argv[1]
data = load(f); u8 = np.frombuffer(data, np.uint8)
db = Db(data); db.segment()
# flag byte histogram at record starts that the 4-run segmenter did not cover, using stride-73 member-like records:
# look for headers [a>0][r>0][flag][key>0] and count flags
L = len(data)
for fl in (0, 1, 2, 3, 4, 5, 6, 8, 16, 32, 64, 128):
    cand = np.nonzero(u8[8:] == fl)[0]; cand = cand[cand + 13 < L]
    a = db.I(cand); r = db.I(cand + 4); k = db.I(cand + 9)
    ok = (a > 1000) & (r > 1000) & (k > 1000) & (a < 2**31) & (np.abs(a - k) < 5e7)
    print('flag', fl, 'plausible headers', int(ok.sum()))
