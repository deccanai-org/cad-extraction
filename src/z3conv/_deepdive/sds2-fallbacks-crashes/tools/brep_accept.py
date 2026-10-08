"""Run brep_placed's acceptance (parse -> solid -> weight window / extents) on listed pieces with two decode trees and
report which pieces each accepts as exact. usage: brep_accept.py <decodeA> <decodeB> <job> <ids|file>"""
import sys, os, subprocess, json
A, B, job, ids = sys.argv[1:5]
if os.path.exists(ids): ids = open(ids).read().replace('subm/', '')
code = r'''
import sys, json, numpy as np
sys.path.insert(0, sys.argv[1]); job = sys.argv[2]; ids = [int(x) for x in sys.argv[3].split(',') if x]
import to_step2 as T2
from piece_table import read_pieces
P = read_pieces(job); out = {}
for sid in ids:
    p = P.get(sid)
    if p is None: out[sid] = 'no table entry'; continue
    sh = T2.brep_placed(job, sid, p, np.eye(3), np.zeros(3))
    out[sid] = 'exact' if sh is not None else T2.BREP_WHY.get((job, sid), '?')
print(json.dumps(out))
'''
res = {}
for nm, d in (('A', A), ('B', B)):
    r = subprocess.run([sys.executable, '-c', code, d, job, ids], capture_output=True, text=True)
    res[nm] = json.loads(r.stdout.strip().splitlines()[-1])
import collections
ca = collections.Counter(v if v == 'exact' else v.split(' (')[0][:60] for v in res['A'].values())
cb = collections.Counter(v if v == 'exact' else v.split(' (')[0][:60] for v in res['B'].values())
print(os.path.basename(job.rstrip('/')), 'pieces', len(res['A']))
print('  A', dict(ca)); print('  B', dict(cb))
print('  newly exact in B:', [k for k in res['B'] if res['B'][k] == 'exact' and res['A'][k] != 'exact'])
