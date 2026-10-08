"""Type-field consistency check: for each member, compare the decoded type with its geometry/section, reading the type
from slot n (as v4 does) and from slots n-1 / n+1.  A correct type offset gives ~0 contradictions
(JOIST <-> joist designation, COLUMN <-> vertical, BEAM/BRACE <-> non-vertical rolled shape)."""
import sys, os, re, collections, glob
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'work/v4p/sds2-step-pipeline/decode'))
import numpy as np
from sds2job import read_members, _ascii, read_version
JS = re.compile(r'^\d+(?:\.\d+)?(K|KCS|LH|DLH|SLH|G|BG|VG)', re.I)

def contradictions(job, shift):
    mems, L = read_members(job)
    idx = open(os.path.join(job, 'mem', 'mem_idx'), 'rb').read(); S = L['slot']
    bad = ok = 0; ex = []
    for m in mems:
        o = (m.id + shift) * S + L['type']
        t = _ascii(idx[o:o + 32])
        if m.section is None or t not in ('BEAM', 'COLUMN', 'JOIST', 'VERTICAL BRACE', 'HORIZONTAL BRACE'):
            continue
        d = np.subtract(m.p2, m.p1); l = np.linalg.norm(d)
        if not l:
            continue
        vert = abs(d[2]) / l > 0.99; js = bool(JS.match(m.section.name))
        good = (t == 'JOIST') == js and (t != 'COLUMN' or vert) and (t != 'BEAM' or not vert)
        ok += good; bad += not good
        if not good and len(ex) < 3:
            ex.append((m.id, t, m.section.name, 'vert' if vert else 'horiz'))
    return ok, bad, ex, L

if __name__ == '__main__':
    for job in sys.argv[1:]:
        try:
            res = {s: contradictions(job, s) for s in (-1, 0, 1)}
        except Exception as e:
            print(os.path.basename(job.rstrip('/')), 'ERR', e); continue
        L = res[0][3]
        print(f"{os.path.basename(job.rstrip('/'))[:40]:40s} v{read_version(job)} slot {L['slot']} type@{L['type']}",
              ' '.join(f"shift{s:+d}: ok {r[0]} bad {r[1]}" for s, r in res.items()), res[0][2])
