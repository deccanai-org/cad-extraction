import sys, json, pickle, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
tag, eng = sys.argv[1], sys.argv[2]
db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L[eng]['layout'],V,False)
M=[m for m in members(db,pts,cs,lay) if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
want=[float(x) for x in sys.argv[3].split(',')]   # member lengths to show
shown=set()
for m in M:
    if not any(abs(m['L']-w)<0.05 for w in want): continue
    r = int(db.lookup([int(db.I([m['off'] + lay['poly_field']])[0])], lay['poly_stride'])[0])
    if lay.get('poly_field2'):
        r = int(db.lookup([int(db.I([r + lay['poly_field2']])[0])], lay['poly_stride2'])[0])
    if r in shown: continue
    shown.add(r); S = lay.get('poly_stride2') or lay['poly_stride']
    print('== L', round(m['L'],1), 'rec', r, 'stride', S)
    for base in range(21, S - 3, 40):
        n = min(10, (S - base) // 4)
        f = db.F(r + base + 4*np.arange(n)); i = db.I(r + base + 4*np.arange(n))
        print(f'  +{base:3d} f', [round(float(x),3) for x in f])
        print(f'  +{base:3d} i', [int(x) for x in i])
    print('  head ints', [int(x) for x in db.I(r + np.arange(0, 21, 4))], ' tail bytes', db.b[r+301:r+S].hex())
    if len(shown) >= 3: break
