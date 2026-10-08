#!/usr/bin/env python3
"""gtime2.py PIPE JOB N : build the N most-placed gratings, time BRepCheck / volume / STEP round trip per solid."""
import sys, os, re, json, time, collections
import numpy as np
PIPE, job, N = sys.argv[1], sys.argv[2], int(sys.argv[3])
sys.path.insert(0, os.path.join(PIPE, 'decode'))
from piece_table import read_pieces, slot_size, LAYOUTS
from instances import material_instances
from sds2job import read_members
import brep, grating
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
b = open(os.path.join(job, 'subm', 'subm_idx'), 'rb').read()
S = LAYOUTS[slot_size(b)]['slot']
pieces = read_pieces(job)
gr = {k: p for k, p in pieces.items() if re.match(r'G[TR]\d', p['name'])}
mems, _ = read_members(job); placed = collections.Counter()
for m in mems:
    try: _, inst = material_instances(job, m.id, pieces)
    except Exception: continue
    for sid, M, o in inst:
        if sid in gr: placed[sid] += 1
def cnt(sh, t):
    e = TopExp_Explorer(sh, t); n = 0
    while e.More(): n += 1; e.Next()
    return n
tot = collections.Counter()
for k, n in placed.most_common(N):
    p = gr[k]; r = brep.parse(open(os.path.join(job, 'subm', str(k)), 'rb').read())
    t0 = time.time(); sh, info = grating.build(r[0], r[1], p['wt'], b[k * S:(k + 1) * S]); tb = time.time() - t0
    if sh is None: print(k, p['name'], 'not built', info.get('why')); continue
    t0 = time.time(); ok = BRepCheck_Analyzer(sh).IsValid(); tc = time.time() - t0
    t0 = time.time(); g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); tv = time.time() - t0
    print(f"{k} {p['name']} placed {n} faces {cnt(sh, TopAbs_FACE)} edges {cnt(sh, TopAbs_EDGE)} build {tb:.1f}s check {tc:.2f}s vol {tv:.2f}s valid {ok}", flush=True)
    tot['check_x_placed'] += tc * n; tot['vol_x_placed'] += tv * n
print(dict(tot))
