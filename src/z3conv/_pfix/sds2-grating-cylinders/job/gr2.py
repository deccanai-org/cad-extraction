#!/usr/bin/env python3
"""gr2.py PIPE JOB OUT.json : grating pieces (G[TR] names): B-rep topology (bodies, edge use, closure per body),
volume vs SDS2 weight, and the piece-table slot fields (bar thickness / depth / spacing / cross bars / size)."""
import sys, os, re, json, struct, collections
import numpy as np
PIPE, job, outp = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, os.path.join(PIPE, 'decode'))
from piece_table import read_pieces, slot_size, LAYOUTS
from instances import material_instances
from sds2job import read_members, read_version
import brep
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
res = dict(job=job, version=read_version(job))
b = open(os.path.join(job, 'subm', 'subm_idx'), 'rb').read()
key = slot_size(b); Lo = LAYOUTS[key]; S = Lo['slot']
res['slot_layout'] = str(key)
pieces = read_pieces(job)
gr = {k: p for k, p in pieces.items() if re.match(r'G[TR]\d', p['name'])}
res['n_grating_pieces'] = len(gr)
# placements
mems, _ = read_members(job)
placed = collections.Counter(); mtype = collections.defaultdict(collections.Counter)
for m in mems:
    try:
        _, inst = material_instances(job, m.id, pieces)
    except Exception:
        continue
    for sid, M, o in inst:
        if sid in gr:
            placed[sid] += 1; mtype[sid][m.type] += 1
res['placed'] = sum(placed.values())
fmt = Lo['f']; fs = struct.calcsize(fmt)
def vol(sh):
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); return abs(g.Mass()) / 25.4 ** 3
out = []
for k in sorted(gr, key=lambda k: -placed[k]):
    p = gr[k]
    s = b[k * S:(k + 1) * S]
    # all plausible f64/f32 numbers in the slot after the name/weight region
    nums = []
    for o in range(0, S - fs + 1, 2 if fs == 8 else 2):
        v = struct.unpack(fmt, s[o:o + fs])[0]
        if np.isfinite(v) and 1e-4 < abs(v) < 2e4 and abs(v * 64 - round(v * 64)) < 1e-6:
            nums.append((o, round(float(v), 5)))
    d = dict(sid=k, name=p['name'], wt=round(p['wt'], 3), placed=placed[k], member_types=dict(mtype[k]), slot_nums=nums[:80])
    fp = os.path.join(job, 'subm', str(k))
    if not os.path.exists(fp):
        d['file'] = 'missing'; out.append(d); continue
    data = open(fp, 'rb').read()
    r = brep.parse(data)
    if r is None:
        d['brep'] = None; out.append(d); continue
    V, F = r
    used = sorted({i for f in F for i in f})
    d['nv'], d['nf'] = len(V), len(F)
    d['ptp'] = np.round(np.ptp(V[used], 0), 4).tolist(); d['lo'] = np.round(V[used].min(0), 4).tolist()
    d['face_sizes'] = collections.Counter(len(f) for f in F).most_common(8)
    E = collections.Counter()
    for f in F:
        for l in brep.loops_of(f):
            for a, c in zip(l, l[1:] + l[:1]): E[(min(a, c), max(a, c))] += 1
    d['edge_use'] = dict(collections.Counter(E.values()))
    parts = brep.bodies(F)
    d['n_bodies'] = len(parts)
    bod = []
    tot = 0.0; nclosed = 0
    for P in parts:
        u = sorted({i for f in P for i in f})
        sh = brep._solid(V, P)
        if sh is None:
            try:
                sh = brep._solid(V, brep.conform(V, P))
            except Exception:
                sh = None
        vv = vol(sh) if sh is not None else None
        if vv: tot += vv; nclosed += 1
        if len(bod) < 60:
            bod.append(dict(nf=len(P), ptp=np.round(np.ptp(V[u], 0), 4).tolist(), lo=np.round(V[u].min(0), 4).tolist(),
                            closed=sh is not None, vol=None if vv is None else round(vv, 4)))
    d['bodies'] = bod
    d['bodies_closed'] = nclosed
    d['vol_closed_bodies_in3'] = round(tot, 3)
    d['steel_lb_closed_bodies'] = round(tot * 0.2836, 3)
    whole = brep.solid(V, F)
    d['whole_solid'] = whole is not None
    if whole is not None:
        d['whole_vol_lb'] = round(vol(whole) * 0.2836, 3)
    # holes in the tail (grating cut-outs?)
    try:
        d['holes'] = len(brep.holes(data))
    except Exception:
        d['holes'] = 'err'
    out.append(d)
res['pieces'] = out
res['summary'] = dict(pieces=len(out), placed=sum(placed.values()),
                      whole_solid=sum(1 for d in out if d.get('whole_solid')),
                      all_bodies_closed=sum(1 for d in out if d.get('n_bodies') and d.get('bodies_closed') == d.get('n_bodies')),
                      nobrep=sum(1 for d in out if 'brep' in d and d['brep'] is None), missing=sum(1 for d in out if d.get('file') == 'missing'))
json.dump(res, open(outp, 'w'), default=lambda o: o.item() if hasattr(o, 'item') else str(o))
print(job, res['version'], res['slot_layout'], json.dumps(res['summary']))
