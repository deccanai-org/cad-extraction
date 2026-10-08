#!/usr/bin/env python3
"""pipe1.py PIPE JOB OUT.json : round HSS / PIPE pieces whose exact B-rep is refused: why, and whether the stored
geometry (faces or vertices) is a plain straight tube (two coaxial circles at two perpendicular end stations)."""
import sys, os, re, json, collections
import numpy as np
PIPE, job, outp = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, os.path.join(PIPE, 'decode'))
import to_step2 as T2, brep
from instances import material_instances, subm_vertices, piece_vertices
from piece_table import read_pieces, kind
from sds2job import read_members, read_shapes
pieces = read_pieces(job); shapes = read_shapes(job); mems, _ = read_members(job)
placed = collections.Counter(); first = {}
for m in mems:
    try: _, inst = material_instances(job, m.id, pieces)
    except Exception: continue
    for sid, M, o in inst:
        p = pieces.get(sid)
        if not p or kind(p) != 'rolled' or p['sec'] not in shapes: continue
        sh = shapes[p['sec']]
        rnd = sh.family in ('PIPE', 'HS') or (sh.family == 'HSS' and sh.name.lower().count('x') == 1)
        if not rnd: continue
        placed[sid] += 1; first.setdefault(sid, (M, o))
out = []; summ = collections.Counter()
for sid, n in placed.items():
    p = pieces[sid]; sh = shapes[p['sec']]; M, o = first[sid]
    T2.SHARED = True
    ex = T2.brep_placed(job, sid, p, M, o)
    if ex is not None:
        summ['exact'] += n; continue
    why = T2.BREP_WHY.get((job, sid))
    d = dict(sid=sid, name=p['name'], sec=sh.name, d=sh.d, t=sh.tf or sh.tw, L=p['L'], wt=p['wt'], placed=n, why=why)
    r = None
    try: r = brep.parse(open(os.path.join(job, 'subm', str(sid)), 'rb').read())
    except Exception: pass
    V = np.asarray(r[0])[sorted({i for f in r[1] for i in f})] if r is not None else subm_vertices(job, sid)
    if V is None or len(V) < 6:
        d['geom'] = 'none'; summ['nogeom'] += n; out.append(d); continue
    d['nv'] = len(V); d['faces'] = None if r is None else collections.Counter(len(f) for f in r[1]).most_common(5)
    c = V.mean(0); u, s, vt = np.linalg.svd(V - c, full_matrices=False); a = vt[0]
    t = (V - c) @ a; rr = np.linalg.norm((V - c) - np.outer(t, a), axis=1)
    d['ptp_t'] = round(float(np.ptp(t)), 4); d['r_q'] = [round(float(x), 4) for x in np.percentile(rr, [0, 25, 50, 75, 100])]
    tl = np.round(t, 3); d['stations'] = len(set(tl)); d['radii'] = len(set(np.round(rr, 3)))
    d['axis_local'] = np.round(a, 4).tolist()
    straight = d['stations'] <= 2 and abs(rr.max() - sh.d / 2) < 0.01
    d['plain_tube_candidate'] = bool(straight)
    summ['plain' if straight else 'notplain'] += n
    out.append(d)
json.dump(dict(job=job, summary=dict(summ), pieces=out), open(outp, 'w'), default=str)
print(job, dict(summ))
