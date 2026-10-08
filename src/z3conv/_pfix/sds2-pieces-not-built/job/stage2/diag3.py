#!/usr/bin/env python3
"""diag_pieces.py DECODE_DIR JOB SKIPPED_CSV OUT.json -> replay the v5.4 builder decisions for every skipped piece"""
import sys, os, json, csv, collections, re, traceback
sys.path.insert(0, sys.argv[1])
import numpy as np
import to_step2 as T2, brep
from piece_table import read_pieces, kind, slot_size
from sds2job import read_shapes, read_members
from instances import material_instances, piece_vertices, subm_vertices
job, skp, outp = sys.argv[2], sys.argv[3], sys.argv[4]
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
MM = 25.4
pieces = read_pieces(job); shapes = read_shapes(job)
mems, _ = read_members(job); mtype = {m.id: m.type for m in mems}
rows = list(csv.DictReader(open(skp)))
by = collections.defaultdict(list)
for r in rows: by[int(r['piece'])].append(r)


def vol(sh):
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); return abs(g.Mass()) / MM ** 3


def ext(sh):
    b = Bnd_Box(); BRepBndLib.Add_s(sh, b); lo, hi = b.CornerMin(), b.CornerMax()
    return [round((hi.X() - lo.X()) / MM, 2), round((hi.Y() - lo.Y()) / MM, 2), round((hi.Z() - lo.Z()) / MM, 2)]


out = []
for sid, rs in sorted(by.items()):
    r0 = rs[0]
    p = pieces.get(sid)
    d = dict(sid=sid, reason=r0['reason'], n_inst=len(rs), name=r0['name'], member_types=sorted({r['member_type'] for r in rs}))
    if p is None:
        d['piece'] = None; out.append(d); continue
    d['piece'] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in p.items()}
    d['kind'] = kind(p); d['turned'] = bool(T2.TURNED.match(p['name']))
    d['sec_name'] = shapes[p['sec']].name if p['sec'] in shapes else None
    fp = os.path.join(job, 'subm', str(sid))
    d['file_bytes'] = os.path.getsize(fp) if os.path.exists(fp) else None
    try:
        data = open(fp, 'rb').read()
        r = brep.parse(data)
        if r is not None:
            V, F = r
            used = sorted({i for f in F for i in f})
            d['brep'] = dict(nv=len(V), nf=len(F), used=len(used), ext=[round(float(x), 3) for x in np.ptp(V[used], 0)] if used else None,
                             vmax=round(float(np.abs(V[used]).max()), 2) if used else None)
            sh = brep.solid(V, F)
            d['brep']['solid'] = sh is not None
            if sh is not None:
                d['brep']['vol_in3'] = round(vol(sh), 3); d['brep']['wt_ratio'] = round(vol(sh) * 0.2836 / p['wt'], 3) if p['wt'] > 0 else None
                d['brep']['solid_ext'] = ext(sh)
            else:
                E = collections.Counter()
                for f in F:
                    for l in brep.loops_of(f):
                        for a, b in zip(l, l[1:] + l[:1]): E[(min(a, b), max(a, b))] += 1
                d['brep']['edge_use'] = dict(collections.Counter(min(v, 4) for v in E.values()))
                d['brep']['degenerate_faces'] = sum(1 for f in F if brep.loops_of(f) and brep._area(V[brep.loops_of(f)[0]]) < 1e-9)
        else:
            d['brep'] = None
        H = brep.holes(data); d['holes'] = len(H)
    except Exception as e:
        d['brep_err'] = f'{type(e).__name__}: {e}'
    try:
        Vp = piece_vertices(job, sid); d['piece_vertices'] = None if Vp is None else len(Vp)
        if Vp is not None and len(Vp): d['pv_ext'] = [round(float(x), 3) for x in np.ptp(Vp, 0)]; d['pv_absmax'] = round(float(np.abs(Vp).max()), 2)
        Vs = subm_vertices(job, sid); d['subm_vertices'] = None if Vs is None else len(Vs)
        Vm = T2.mesh_vertices(job, sid); d['mesh_vertices'] = None if Vm is None else len(Vm)
        if Vm is not None and len(Vm): d['mv_ext'] = [round(float(x), 3) for x in np.ptp(Vm, 0)]
    except Exception as e:
        d['vert_err'] = f'{type(e).__name__}: {e}'
    # replay brep_placed + special_solid at an identity placement
    M = np.eye(3); o = np.zeros(3)
    try:
        T2.SHARED = False
        bp = T2.brep_placed(job, sid, p, M, o)
        d['brep_placed'] = bp is not None; d['brep_why'] = T2.BREP_WHY.get((job, sid))
        if bp is not None: d['brep_placed_ext'] = ext(bp)
    except Exception as e:
        d['brep_placed_err'] = f'{type(e).__name__}: {e}'
    try:
        sh, k2 = T2.special_solid(job, sid, p, M, o)
        d['special'] = None if sh is None else dict(kind=k2, ext=ext(sh), absurd=T2._absurd(sh), note=T2.SPECIAL_NOTE)
        if sh is None: d['special_why'] = k2
    except Exception as e:
        d['special_err'] = f'{type(e).__name__}: {e}'
    try:
        if p.get('sec', 0) in shapes:
            s_ = shapes[p['sec']]
            d['section'] = dict(name=s_.name, weight=getattr(s_, 'weight', None), d=getattr(s_, 'd', None), bf=getattr(s_, 'bf', None))
            if (s_.weight or 0) > 0 and p.get('L', 0) > 0:
                d['nominal_lb'] = round(s_.weight * p['L'] / 12, 2)
        if p.get('L', 0) > 0 and p.get('W', 0) > 0 and p.get('T', 0) > 0:
            d['table_slab_lb'] = round(p['L'] * p['W'] * p['T'] * 0.2836, 2)
        if hasattr(T2, 'table_standin'):
            Vx = T2.piece_vertices(job, sid) if d.get('kind') in ('plate', 'rolled') else T2.subm_vertices(job, sid)
            ts = T2.table_standin(Vx, p, shapes.get(p['sec']) if d.get('kind') == 'rolled' else None)
            d['table_standin_lb'] = None if ts is None else round(vol(ts) * 0.2836, 2)
    except Exception as e:
        d['extra_err'] = f'{type(e).__name__}: {e}'
    if hasattr(T2, 'source_gap'):
        try: d['gap_b'] = T2.source_gap(job, sid, p)
        except Exception as e: d['gap_b'] = f'err {e}'
    out.append(d)
json.dump(dict(job=os.path.basename(job), slot=str(slot_size(open(os.path.join(job, 'subm', 'subm_idx'), 'rb').read(64 * 1024))), pieces=out), open(outp, 'w'), indent=0, default=str)
print(os.path.basename(job), len(out), 'pieces')
