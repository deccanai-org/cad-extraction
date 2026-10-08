"""Per member with SDS2 bolt records: which placement frame puts its records on decoded hole stacks (nominal stacks
of a v4 bolt_diag run)? frames tried: header block (v4 default when frames.get(n) is None), the 0xE8 main-material
instance (v4 'frames'), every other instance of the member, and the instance whose piece is the member's section.
usage: bolt_frames2.py <decode dir> <job> <bolt_diag.json>"""
import sys, os, json, struct, collections, numpy as np
sys.path.insert(0, sys.argv[1])
import bolts as BR
from piece_table import read_pieces
from instances import material_instances
from sds2job import read_members, read_shapes
from scipy.spatial import cKDTree
job = sys.argv[2]
D = json.load(open(sys.argv[3]))
st = [(np.array(r['entry']), np.array(r['axis']), r['grip'], r['dia']) for r in D['nominal']]
mid = np.array([e + a * g / 2 for e, a, g, d in st]); tree = cKDTree(mid)
P = read_pieces(job); shapes = read_shapes(job)
mems, _ = read_members(job); M_ = {m.id: m for m in mems}
def on_stack(head, axis):
    if not np.isfinite(head).all() or np.abs(head).max() > 1e7: return None
    for j in tree.query_ball_point(head, 8.0):
        e, a, g, d = st[j]; v = head - e
        if np.linalg.norm(np.cross(v, a)) < 1 / 16 and abs(abs(axis @ a) - 1) < 1e-3 and -0.25 <= v @ a <= g + 0.25:
            return j
    return None
tot = collections.Counter(); per = []
for n in sorted(M_):
    try: raw = BR.member_bolts(job, n, (np.eye(3), np.zeros(3)))
    except Exception: continue
    if not raw: continue
    main, inst = material_instances(job, n, P)
    b = open(os.path.join(job, 'mem', str(n)), 'rb').read()
    Rh = np.array(struct.unpack('>9d', b[0x88:0xD0])).reshape(3, 3); Oh = np.array(struct.unpack('>3d', b[0xD0:0xE8]))
    sec = M_[n].section.name if M_[n].section else None
    cands = {'header': (Rh, Oh)}
    for k, (sid, M, o) in enumerate(inst):
        tag = ('main0xE8' if sid == main else 'section' if P.get(sid, {}).get('name') == sec else 'other') + f'#{k}'
        cands.setdefault(tag, (M, o))
    res = {}
    for nm, (M, o) in cands.items():
        hits = sum(on_stack(o + M.T @ r['head'], M.T @ r['axis']) is not None for r in raw)
        res[nm] = hits
    best = max(res, key=res.get)
    v4 = res.get(next((k for k in res if k.startswith('main0xE8')), 'header'), 0)
    per.append((n, M_[n].type, sec, len(raw), v4, best, res[best]))
    tot['records'] += len(raw); tot['v4 frame hits'] += v4; tot['best frame hits'] += res[best]
    tot['best=' + best.split('#')[0]] += 1
print(dict(tot))
for x in per:
    if x[5].split('#')[0] != 'main0xE8' and x[6] > x[4]: print('  member', x)
