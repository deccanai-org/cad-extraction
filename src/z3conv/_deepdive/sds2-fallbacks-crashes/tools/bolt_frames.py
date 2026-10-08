"""For nominal stacks of a v4 bolt_diag run, test which frame maps the member's SDS2 bolt records onto the stacks.
usage: bolt_frames.py <decode dir> <job> <bolt_diag.json>"""
import sys, os, json, struct, collections, numpy as np
sys.path.insert(0, sys.argv[1])
import bolts as BR
from piece_table import read_pieces
from instances import material_instances
from sds2job import read_members
job = sys.argv[2]
D = json.load(open(sys.argv[3]))
st = [(np.array(r['entry']), np.array(r['axis']), r['grip'], r['dia']) for r in D['nominal']]
P = read_pieces(job)
mems, _ = read_members(job)
mids = {r['nearest_on_axis']['member'] for r in D['nominal'] if r['nearest_on_axis']}
print('members near nominal stacks', sorted(mids)[:20])
def score(recs):
    """stacks whose axis line passes within 1/16 in of a record head, parallel, head inside / at the stack span"""
    hit = 0
    for e, a, g, d in st:
        ok = False
        for r in recs:
            v = r['head'] - e; lat = np.linalg.norm(np.cross(v, a)); al = v @ a
            if lat < 1/16 and abs(abs(r['axis'] @ a) - 1) < 1e-3 and -0.25 <= al <= g + 0.25:
                ok = True; break
        hit += ok
    return hit
for n in sorted(mids)[:6]:
    b = open(os.path.join(job, 'mem', str(n)), 'rb').read()
    Rh = np.array(struct.unpack('>9d', b[0x88:0xD0])).reshape(3, 3); Oh = np.array(struct.unpack('>3d', b[0xD0:0xE8]))
    main, inst = material_instances(job, n, P)
    fr = {('inst main', sid == main, k): (M, o) for k, (sid, M, o) in enumerate(inst)}
    cands = {'header': (Rh, Oh), 'header^T': (Rh.T, Oh)}
    for k, (M, o) in list(fr.items())[:12]:
        cands[str(k)] = (M, o); cands[str(k) + '^T'] = (M.T, o)
    raw = BR.member_bolts(job, n, (np.eye(3), np.zeros(3)))
    print(f'member {n}: {len(raw)} records; main sid {main}; instances {len(inst)}; header==main inst?',
          any(np.allclose(M, Rh) and np.allclose(o, Oh) for (_, M, o) in inst))
    for nm, (M, o) in cands.items():
        recs = [dict(r, head=o + M.T @ r['head'], axis=M.T @ r['axis']) for r in raw]
        s = score(recs)
        if s: print(f'   frame {nm}: stacks matched {s}/{len(st)}')
