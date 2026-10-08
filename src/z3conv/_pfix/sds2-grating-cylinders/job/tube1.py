#!/usr/bin/env python3
"""tube1.py PIPE JOB OUT.json : round HSS / pipe pieces whose exact B-rep is refused -> round_tube_local() outcome."""
import sys, os, json, collections
import numpy as np
PIPE, job, outp = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, os.path.join(PIPE, 'decode'))
import to_step2 as T2
from instances import material_instances
from piece_table import read_pieces, kind
from sds2job import read_members, read_shapes
pieces = read_pieces(job); shapes = read_shapes(job); mems, _ = read_members(job)
placed = collections.Counter(); first = {}
for m in mems:
    try: _, inst = material_instances(job, m.id, pieces)
    except Exception: continue
    for sid, M, o in inst:
        p = pieces.get(sid)
        if not p or kind(p) != 'rolled' or not T2._round_section(shapes.get(p['sec'])): continue
        placed[sid] += 1; first.setdefault(sid, (M, o))
T2.SHARED = True
summ = collections.Counter(); out = []
for sid, n in placed.items():
    p = pieces[sid]; s = shapes[p['sec']]; M, o = first[sid]
    if T2.brep_placed(job, sid, p, M, o) is not None:
        summ['exact_brep'] += n; continue
    sh = T2.round_tube_local(job, sid, p, s)
    info = {k: v for k, v in T2.TUBE_INFO.get((job, sid), {}).items() if k != 'solid'}
    res = 'tube' if sh is not None else 'not_plain'
    if sh is not None:
        from OCP.GProp import GProp_GProps
        from OCP.BRepGProp import BRepGProp
        g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); info['occ_lb'] = round(abs(g.Mass()) / 25.4 ** 3 * 0.2836, 3)
        pl = T2._place(sh, M, o); info['placed_ok'] = pl is not None
    summ[res] += n
    out.append(dict(sid=sid, name=p['name'], sec=s.name, d=s.d, t=s.tf or s.tw, L=p['L'], wt=round(p['wt'], 3), placed=n,
                    brep_why=T2.BREP_WHY.get((job, sid)), res=res, **info))
json.dump(dict(job=job, summary=dict(summ), pieces=out), open(outp, 'w'), default=str)
print(job, dict(summ))
