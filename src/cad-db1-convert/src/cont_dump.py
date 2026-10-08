import sys, numpy as np; sys.path.insert(0,'src')
from db1dec import load
b=load('pairs/data/8.53_0575f7270f.db1')
def I(o): return int(np.frombuffer(b[o:o+4],'<i4')[0])
def F(o): return float(np.frombuffer(b[o:o+4],'<f4')[0])
for r in (13291280, 13291621):
    print('== rec', r, 'objid', I(r), 'ref', I(r+4), 'byte8', b[r+8], 'seq', I(r+9), 'h13', I(r+13), 'h17', I(r+17))
    for base in range(21, 341, 40):
        print(f'  +{base:3d}', [round(F(base+r+4*i),2) for i in range(10)], [I(base+r+4*i) for i in range(10)] if base==221 else '')
