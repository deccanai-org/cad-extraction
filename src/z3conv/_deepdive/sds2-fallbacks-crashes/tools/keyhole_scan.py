"""Corpus scan: piece files whose v4 brep.solid() fails, and how many the keyhole-loop split repairs.
usage: keyhole_scan.py <job> [<job> ...]"""
import sys, os, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'v4', 'sds2-step-pipeline', 'decode'))
import brep
from piece_table import read_pieces

def split_loops(f):
    out, cur = [], []
    for i in f:
        if cur and i == cur[-1]: continue
        if i in cur:
            j = cur.index(i); seg = cur[j:]; cur = cur[:j + 1]
            if len(seg) >= 3: out.append(seg)
        else: cur.append(i)
    if len(cur) >= 3 and cur[0] == cur[-1]: cur = cur[:-1]
    return ([cur] if len(cur) >= 3 else []) + out

def encode(loops):
    nf = []
    for l in loops: nf += l + ([l[0]] if len(loops) > 1 else [])
    return nf

for job in sys.argv[1:]:
    P = read_pieces(job)
    c = collections.Counter(); names = collections.Counter()
    for sid, p in P.items():
        fp = os.path.join(job, 'subm', str(sid))
        if not os.path.exists(fp): continue
        r = brep.parse(open(fp, 'rb').read())
        if r is None: c['parse None'] += 1; continue
        V, F = r
        kh = any(encode(split_loops(f)) != f for f in F)
        if kh: c['has keyhole faces'] += 1
        s = brep.solid(V, F)
        if s is not None: c['solid ok (v4)'] += 1; continue
        c['solid fails (v4)'] += 1
        if kh:
            s2 = brep.solid(V, [encode(split_loops(f)) for f in F])
            if s2 is not None: c['repaired by keyhole split'] += 1; names[p['name'].split()[0][:10]] += 1
    print(os.path.basename(job), dict(c), names.most_common(8))
