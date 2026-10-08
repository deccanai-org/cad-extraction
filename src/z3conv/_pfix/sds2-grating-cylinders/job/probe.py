#!/usr/bin/env python3
"""probe.py PIPE_DIR JOB OUT.json : rods (TURNED names that fall to the straight-rod guess) + grating pieces summary"""
import sys, os, json, re, collections, struct
import numpy as np
PIPE, job, outp = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, os.path.join(PIPE, 'decode'))
import to_step2 as T2
from instances import material_instances, subm_vertices, piece_vertices
from piece_table import read_pieces, kind
from sds2job import read_members
import brep
pieces = read_pieces(job)
mems, _ = read_members(job)
res = dict(job=job, main_files=sorted(os.listdir(os.path.join(job, 'main'))), rods=[], grating=[], turned_ok=collections.Counter())
placed = collections.Counter(); seen = set()
for m in mems:
    try:
        _, inst = material_instances(job, m.id, pieces)
    except Exception as e:
        continue
    for sid, M, o in inst:
        p = pieces.get(sid)
        if not p: continue
        placed[sid] += 1
        if sid in seen: continue
        nm = p['name']
        if T2.TURNED.match(nm):
            seen.add(sid)
            Vt = subm_vertices(job, sid); V = T2.mesh_vertices(job, sid)
            segs = T2.turned_local(Vt) if Vt is not None and len(Vt) >= 6 else None
            src = 'subm'
            if not segs and V is not None:
                segs = T2.turned_local(V); src = 'mesh'
            if segs:
                res['turned_ok'][nm] += 1; continue
            b = open(os.path.join(job, 'subm', str(sid)), 'rb').read()
            r = brep.parse(b)
            d = dict(sid=sid, name=nm, member_type=m.type, p={k: (round(v, 4) if isinstance(v, float) else v) for k, v in p.items()},
                     file_bytes=len(b), M=np.round(M, 4).tolist(), o=np.round(o, 3).tolist(),
                     n_subm=None if Vt is None else len(Vt), n_mesh=None if V is None else len(V),
                     brep=None if r is None else dict(nv=len(r[0]), nf=len(r[1]), face_sizes=collections.Counter(len(f) for f in r[1]).most_common(6)))
            for lab, X in (('subm', Vt), ('mesh', V)):
                if X is None or len(X) < 3: continue
                X = np.asarray(X, float)
                c = X.mean(0); u, s, vt = np.linalg.svd(X - c, full_matrices=False)
                d[lab + '_ptp'] = np.round(np.ptp(X, 0), 4).tolist()
                d[lab + '_sv'] = np.round(s / np.sqrt(len(X)), 4).tolist()
                d[lab + '_axis'] = np.round(vt[0], 4).tolist()
                ax = vt[0]; t = (X - c) @ ax; rr = np.linalg.norm((X - c) - np.outer(t, ax), axis=1)
                d[lab + '_radial'] = [round(float(rr.min()), 4), round(float(np.median(rr)), 4), round(float(rr.max()), 4)]
                if len(res['rods']) < 40:
                    d[lab + '_V'] = np.round(X[:400], 5).tolist()
            if r is not None and len(res['rods']) < 40:
                d['brep_V'] = np.round(np.asarray(r[0])[:600], 5).tolist(); d['brep_F'] = [list(map(int, f)) for f in r[1][:400]]
            res['rods'].append(d)
        elif re.match(r"G[TR]\d", nm):
            seen.add(sid)
            b = open(os.path.join(job, 'subm', str(sid)), 'rb').read()
            r = brep.parse(b)
            d = dict(sid=sid, name=nm, member_type=m.type, member_section=(m.section.name if m.section else None),
                     p={k: (round(v, 4) if isinstance(v, float) else v) for k, v in p.items()}, file_bytes=len(b),
                     brep=None if r is None else dict(nv=len(r[0]), nf=len(r[1]), ptp=np.round(np.ptp(np.asarray(r[0]), 0), 4).tolist()))
            if len(res['grating']) < 6:
                d['hex_head'] = b[:0x2C].hex()
                d['tail_ascii'] = re.findall(rb"[ -~]{4,}", b)[:40]
                d['tail_ascii'] = [x.decode() for x in d['tail_ascii']]
            res['grating'].append(d)
res['placed_rods'] = {str(d['sid']): placed[d['sid']] for d in res['rods']}
res['placed_grating'] = {str(d['sid']): placed[d['sid']] for d in res['grating']}
json.dump(res, open(outp, 'w'), default=lambda o: o.item() if hasattr(o, 'item') else str(o))
print(job, 'rods(no rings)', len(res['rods']), 'placed', sum(res['placed_rods'].values()), 'turned ok', sum(res['turned_ok'].values()),
      'grating', len(res['grating']), 'placed', sum(res['placed_grating'].values()))
