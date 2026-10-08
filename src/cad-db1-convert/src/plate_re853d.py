import sys, json, numpy as np; sys.path.insert(0,'src')
from db1dec import load
b=load('pairs/data/8.53_0575f7270f.db1')
def dump(h, lo, hi):
    for o in range(h+lo, h+hi, 4):
        i=int(np.frombuffer(b[o:o+4],'<i4')[0]); f=float(np.frombuffer(b[o:o+4],'<f4')[0])
        print(f'{o-h:+5d} i={i:>11d} f={f:12.5g}  bytes={b[o:o+4].hex()}')
for h in (16791325, 14461954):
    print('======', h); dump(h, -64, 96)
