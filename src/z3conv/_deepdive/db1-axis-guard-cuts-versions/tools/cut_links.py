"""Old engines: how many ANTIMATERIAL cut parts are linked to a parent through a type-11 relation; for unlinked ones, search the raw
file for any stride-17 relation-like record naming the cut id, and the nearest part (does the cut volume intersect a part?)."""
import sys, os, re, collections, numpy as np
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(H, '..', 'kit_patched'))
import db1old
from db1dec import load
for f in sys.argv[1:]:
    data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    if eng >= 7.5: continue
    M, info, cut_rel = db1old.read(data, eng)
    cuts = [m for m in M if m['cut']]
    linked = {c for v in cut_rel.values() for c in v}
    parents_known = {m['pid'] for m in M}
    un = [m for m in cuts if m['pid'] not in linked]
    o = db1old.Old(data); I = o.I_all; N = len(I) - 400
    # raw occurrences of an unlinked cut id at +12 of a candidate relation record with type 11 at +4
    raw = collections.Counter()
    ex = []
    for m in un:
        occ = np.nonzero(I[:N] == m['pid'])[0]
        kinds = []
        for q in occ:
            q = int(q)
            if q >= 12 and int(I[q - 8]) == 11: kinds.append(('rel11@+12', data[q - 13], int(I[q - 4]) in parents_known))
        raw[bool(kinds)] += 1
        if len(ex) < 4: ex.append((m['pid'], m['prof'], kinds[:3], len(occ)))
    bad_parent = sum(1 for p in cut_rel if p not in parents_known)
    print(os.path.basename(f)[:12], eng, 'cut parts', len(cuts), 'linked', len(cuts) - len(un), 'unlinked', len(un), '| relation parents not a part', bad_parent,
          '| unlinked with a raw type-11 record naming them:', raw.get(True, 0), 'examples', ex)
