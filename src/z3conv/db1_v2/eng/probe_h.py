"""attr-link checks that do not depend on naming habits"""
import sys, json, collections, numpy as np, re
sys.path.insert(0, 'src')
import db1dec; from db1dec import *
L = json.load(open('src/layouts.json')); VA = [v['layout'] for v in L.values() if v.get('layout')]
f, eng = sys.argv[1:3]
data = load(f); db, pts, cs, lay = decode(data, L[eng]['layout'], VA, False)
M = members(db, pts, cs, lay)
print('members', len(M), 'poly_frac', lay.get('poly_frac'), 'poly_ch', lay.get('poly_ch'))
cp = [m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
ok = sum(1 for m in cp if db.outline_points(lay, m)); print('contour plates', len(cp), 'with outline matching L', ok)
seq = {m['seq']: m for m in M}
r69 = db.bystride.get(69); 
if r69 is not None:
    t = db.I(r69 + 13); a = db.I(r69 + 17); b = db.I(r69 + 21)
    c = collections.Counter()
    for t_, p, ch in zip(t, a, b):
        if int(p) in seq and int(ch) in seq: c[(int(t_), seq[int(ch)]['cut'], seq[int(p)]['cut'])] += 1
    print('relations (type, child cut, parent cut)', c.most_common(8))
