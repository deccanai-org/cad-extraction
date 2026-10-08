import sys, json, re, pickle, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
tag='8.53_0575f7270f'
db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L['8.53']['layout'],V,False)
b=db.b
def dump(h, lo=-48, hi=100):
    for o in range(h+lo, h+hi, 4):
        i=int(np.frombuffer(b[o:o+4],'<i4')[0]); f=float(np.frombuffer(b[o:o+4],'<f4')[0])
        print(f'{o-h:+5d} i={i:>11d} f={f:12.4g}')
for h in (13864566, 13864907):
    print('---', h); dump(h)
# member
m_off=47105943
print('--- member'); dump(m_off, 0, 60)
