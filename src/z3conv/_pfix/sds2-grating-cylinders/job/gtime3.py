#!/usr/bin/env python3
"""gtime3.py PIPE JOB N : per grating, BRepCheck time with the full UnifySameDomain vs without, and wires per face."""
import sys, os, re, time, collections
PIPE, job, N = sys.argv[1], sys.argv[2], int(sys.argv[3])
sys.path.insert(0, os.path.join(PIPE, 'decode'))
from piece_table import read_pieces, slot_size, LAYOUTS
from instances import material_instances
from sds2job import read_members
import brep, grating
import OCP.ShapeUpgrade as SU
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_WIRE
from OCP.TopoDS import TopoDS
REAL = SU.ShapeUpgrade_UnifySameDomain
class NoUnify:
    def __init__(self, *a, **k): raise RuntimeError("off")
b = open(os.path.join(job, 'subm', 'subm_idx'), 'rb').read(); S = LAYOUTS[slot_size(b)]['slot']
pieces = read_pieces(job); gr = {k: p for k, p in pieces.items() if re.match(r'G[TR]\d', p['name'])}
mems, _ = read_members(job); placed = collections.Counter()
for m in mems:
    try: _, inst = material_instances(job, m.id, pieces)
    except Exception: continue
    for sid, M, o in inst:
        if sid in gr: placed[sid] += 1
def stats(sh):
    nf = 0; mw = 0; e = TopExp_Explorer(sh, TopAbs_FACE)
    while e.More():
        nf += 1; w = TopExp_Explorer(e.Current(), TopAbs_WIRE); k = 0
        while w.More(): k += 1; w.Next()
        mw = max(mw, k); e.Next()
    return nf, mw
for k, n in placed.most_common(N):
    p = gr[k]; r = brep.parse(open(os.path.join(job, 'subm', str(k)), 'rb').read())
    out = []
    for mode in ('unify', 'nounify'):
        SU.ShapeUpgrade_UnifySameDomain = REAL if mode == 'unify' else NoUnify
        sh, info = grating.build(r[0], r[1], p['wt'], b[k * S:(k + 1) * S])
        if sh is None: out.append(f"{mode}: none {info.get('why')}"); continue
        t0 = time.time(); ok = BRepCheck_Analyzer(sh).IsValid(); tc = time.time() - t0
        g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g)
        nf, mw = stats(sh)
        out.append(f"{mode}: faces {nf} max_wires/face {mw} check {tc:.2f}s valid {ok} lb {abs(g.Mass())/25.4**3*0.2836:.3f}")
    print(k, p['name'], 'placed', n, ' | '.join(out), flush=True)
