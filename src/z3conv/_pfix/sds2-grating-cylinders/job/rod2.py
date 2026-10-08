#!/usr/bin/env python3
"""rod2.py PIPE JOB OUT.json : replay convert()'s rod chain of the given pipeline on every TURNED piece and count
placements per outcome (rings / cap-axis cylinder / exact B-rep / tolerant B-rep / straight guess / not built)."""
import sys, os, json, collections
import numpy as np
PIPE, job, outp = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, os.path.join(PIPE, 'decode'))
import to_step2 as T2
from instances import material_instances
from piece_table import read_pieces
from sds2job import read_members
T2.SHARED = True
pieces = read_pieces(job); mems, _ = read_members(job)
placed = collections.Counter(); first = {}
for m in mems:
    try: _, inst = material_instances(job, m.id, pieces)
    except Exception: continue
    for sid, M, o in inst:
        p = pieces.get(sid)
        if p and T2.TURNED.match(p['name']) and not p['name'].startswith('Conc'):
            placed[sid] += 1; first.setdefault(sid, (M, o))
out = collections.Counter(); names = collections.defaultdict(collections.Counter)
has_any = hasattr(T2, 'turned_any_axis')
for sid, n in placed.items():
    p = pieces[sid]; M, o = first[sid]
    T2.SPECIAL_NOTE = ''
    try:
        sh, k2 = T2.special_solid(job, sid, p, M, o)
    except Exception as e:
        sh, k2 = None, 'err'
    if sh is not None and not T2.SPECIAL_NOTE:
        res = 'cap_axis_cylinder' if has_any and (job, sid) in T2.TURNED_ANY_AXIS else 'rings_cylinder'
    elif sh is not None:
        ex = T2.brep_placed(job, sid, p, M, o) if has_any else None
        if ex is None and has_any:
            ex = T2.rod_brep_placed(job, sid, p, M, o)
            res = 'tolerant_or_rod_brep' if ex is not None else 'straight_guess'
        else:
            res = 'exact_brep' if ex is not None else 'straight_guess'
    else:
        ex = T2.brep_placed(job, sid, p, M, o)
        if ex is None and has_any:
            ex = T2.rod_brep_placed(job, sid, p, M, o)
        if ex is None:
            res = 'not_built'
        else:
            lp = ex[1] if isinstance(ex, tuple) else ex
            res = 'brep_no_rings' + ('' if has_any else '_but_skipped_by_absurd_tuple_bug')
    out[res] += n; names[res][p['name']] += n
json.dump(dict(job=job, outcome=dict(out), names={k: dict(v.most_common(8)) for k, v in names.items()}), open(outp, 'w'))
print(os.path.basename(job), dict(out))
