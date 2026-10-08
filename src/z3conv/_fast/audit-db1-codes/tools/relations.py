"""Which relation records (stride 17: id@0 type@4 id1@8 id2@12) link old-engine bolt groups to parts?"""
import sys, os, collections, numpy as np
KIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'kit_f'); sys.path.insert(0, KIT)
import db1old
from db1dec import load
path = sys.argv[1]
data = load(path)
ban = data[:16]; import re
eng = float(re.search(rb'(\d+\.\d+)', ban).group(1))
M, info, cut_rel = db1old.read(data, eng)
o = db1old.Old(data); N = len(o.I_all) - 400; I = o.I_all
rv = np.zeros(N, bool); Mr = N - 20
rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
rel_off = o.runs(rv, 17)
bolt_ids = {m['pid'] for m in M if m.get('bolt')}
part_ids = {m['pid'] for m in M if not m.get('bolt') and not m.get('cut')}
cut_ids = {m['pid'] for m in M if m.get('cut')}
attr_of = {m['pid']: m['attr'] for m in M}
cnt = collections.Counter(); kinds = collections.defaultdict(collections.Counter)
def k(x):
    return 'bolt' if x in bolt_ids else ('part' if x in part_ids else ('cut' if x in cut_ids else 'other'))
for q in rel_off:
    t = int(I[q + 4]); a = int(I[q + 8]); b = int(I[q + 12])
    cnt[t] += 1; kinds[t][(k(a), k(b))] += 1
print('engine', eng, 'members', len(M), 'bolt groups', len(bolt_ids), 'parts', len(part_ids), 'cuts', len(cut_ids), 'relations', len(rel_off))
for t, n in cnt.most_common():
    print('type', t, n, dict(kinds[t].most_common(6)))
