"""Dump every part the old-engine axis guard (db1old axis_ok is False) drops, with geometry context."""
import sys, os, json, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'kit_snapshot'))
import db1old
from db1dec import load
P_NEW = db1old.PART_NEW; P_OLD = db1old.PART_OLD
for f in sys.argv[1:]:
    data = load(f)
    import re
    eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info, cut_rel = db1old.read(data, eng)
    bad = [m for m in M if m.get('axis_ok') is False]
    print('==', os.path.basename(f)[:12], 'engine', eng, 'parts', len(M), 'axis_agreement', info['axis_agreement'], 'dropped', len(bad))
    o = db1old.Old(data); I = o.I_all; D = o.D_all
    P = P_NEW if eng >= 7.1 else P_OLD
    # point table
    for m in bad:
        q = m['off']
        p1id, p2id = int(I[q + P['p1']]), int(I[q + P['p2']])
        # recompute
        print('  pid', m['pid'], 'prof', m['prof'], 'mat', m['mat'], 'ben', m['ben'], 'L', round(m['L'], 1), 'cut', m['cut'], 'bolt', m['bolt'], 'form', m['form'],
              'npoly', len(m['old_poly']) if m['old_poly'] else 0)
        print('    O', np.round(m['O'], 1), 'xr', np.round(m['xr'], 4), 'y', np.round(m['y'], 4))
        print('    p1id', p1id, 'p2id', p2id, 'cut_rel parent of', cut_rel.get(m['pid']), 'is cutter of', [k for k, v in cut_rel.items() if m['pid'] in v])
        json.dump({}, open(os.devnull, 'w'))
