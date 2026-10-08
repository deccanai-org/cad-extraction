"""hot_diff.py ID : matched Hot-list rows where our weight changed with the patch (after != before): Tekla net / gross vs ours"""
import sys, os, json, gzip, glob, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hot_cmp import parse_hot, load, dec_len, RHO
ID = sys.argv[1]
rows = []
for f in sorted(glob.glob(f'reports/{ID}/Hot_*list*.xsr')): rows += parse_hot(f)
A, B = load(os.environ.get('PIPE_A', 'pipes/kit') + f'/{ID}'), load(os.environ.get('PIPE_B', 'pipes/kitp') + f'/{ID}'); LB = dec_len(ID, 'after')
byk = collections.defaultdict(list)
for pid, (prof, nc, v) in B.items():
    if pid in LB and v: byk[prof].append((LB[pid], pid, nc, v))
for r in rows:
    cand = [c for c in byk.get(r['prof'], []) if abs(c[0] - r['length']) <= 1.0]
    for c in cand:
        a = A.get(c[1])
        if a and a[2] and abs(a[2] - c[3]) > 0.002 * a[2]:
            print(ID, r['mark'], r['prof'], r['length'], 'tekla net', r['net'], 'gross', round(r['gross'], 2), '| ours before', round(a[2] * RHO, 3), 'cuts', a[1], '-> after', round(c[3] * RHO, 3), 'cuts', c[2])
