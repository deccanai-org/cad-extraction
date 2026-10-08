"""rel61.py ID..: relation table scan at stride 61 (7.1-7.4x) vs 17: record counts per type, type-11 coverage of cut parts,
type-10 group->part links"""
import sys, os, re, collections
import numpy as np
W = os.path.dirname(os.path.abspath(__file__)); os.chdir(W)
sys.path.insert(0, os.path.join(W, 'kits', 'i'))
import db1old
from db1dec import load
for a in sys.argv[1:]:
    i = [f[:-4] for f in os.listdir('src') if f.startswith(a)][0]
    data = load(f'src/{i}.db1'); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info, _ = db1old.read(data, eng)
    cuts = {m['pid'] for m in M if m.get('cut')}; parts = {m['pid'] for m in M if not m.get('cut') and not m.get('bolt')}; bolts = {m['pid'] for m in M if m.get('bolt')}
    o = db1old.Old(data); N = len(o.I_all) - 400; I = o.I_all
    for stride in (17, 61):
        rv = np.zeros(N, bool); Mr = N - 20
        rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
        off = o.runs(rv, stride)
        ty = collections.Counter(int(I[q + 4]) for q in off)
        c11 = [(int(I[q + 8]), int(I[q + 12])) for q in off if int(I[q + 4]) == 11]
        cov = len({b for a_, b in c11 if b in cuts}); par = sum(1 for a_, b in c11 if a_ in parts and b in cuts)
        t10 = [(int(I[q + 8]), int(I[q + 12])) for q in off if int(I[q + 4]) == 10]
        g10 = sum(1 for a_, b in t10 if a_ in bolts and b in parts) + sum(1 for a_, b in t10 if b in bolts and a_ in parts)
        print(i[:12], eng, 'stride', stride, 'records', len(off), 'types', ty.most_common(8), '| cuts', len(cuts), 'covered by type 11:', cov,
              'parent is a part:', par, '| type-10 bolt-group<->part links:', g10, 'of', len(t10), 'bolt groups', len(bolts))
