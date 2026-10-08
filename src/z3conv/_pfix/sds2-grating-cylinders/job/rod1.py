#!/usr/bin/env python3
"""rod1.py PIPE JOB OUT.json : every TURNED piece that v5.4's special_solid writes as the straight-rod guess
(mesh_cylinder stand-in): B-rep shape class, straight-cylinder fit residuals, closed-B-rep volume ratio."""
import sys, os, re, json, struct, collections
import numpy as np
PIPE, job, outp = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, os.path.join(PIPE, 'decode'))
import to_step2 as T2
from instances import material_instances, subm_vertices
from piece_table import read_pieces, kind
from sds2job import read_members
import brep
pieces = read_pieces(job)
mems, _ = read_members(job)
placed = collections.Counter(); first = {}; mtypes = collections.defaultdict(collections.Counter)
for m in mems:
    try:
        _, inst = material_instances(job, m.id, pieces)
    except Exception:
        continue
    for sid, M, o in inst:
        p = pieces.get(sid)
        if not p or not T2.TURNED.match(p['name']): continue
        placed[sid] += 1; mtypes[sid][m.type] += 1
        first.setdefault(sid, (M, o))

def frac(s):
    s = s.strip()
    try:
        if ' ' in s:
            a, b = s.split(None, 1); return float(a) + frac(b)
        if '/' in s:
            a, b = s.split('/'); return float(a) / float(b)
        return float(s)
    except Exception:
        return None
DIA = re.compile(r"^(?:RB|RD|AB|DBA|TWS|WS|HS|NS|THD STUD|STUD)\s*(\d+ \d+/\d+|\d+/\d+|\d+(?:\.\d+)?)")

def name_dia(n):
    m = DIA.match(n)
    return frac(m.group(1)) if m else None

def straight_fit(V, F):
    """caps (single-loop faces >= 6 vertices, planar); axis from cap normals; all used vertices on the circle and at
    the two cap stations -> (c0, axis, L, r, resid_r, resid_t, ncap, N)"""
    used = sorted({i for f in F for i in f}); U = V[used]
    caps = []
    for f in F:
        ls = brep.loops_of(f)
        if len(ls) == 1 and len(ls[0]) >= 6:
            P = V[ls[0]]; c = P.mean(0)
            n = sum(np.cross(P[k] - c, P[(k + 1) % len(P)] - c) for k in range(len(P)))
            if np.linalg.norm(n) < 1e-12: continue
            n = n / np.linalg.norm(n)
            caps.append((c, n, len(ls[0]), float(np.abs((P - c) @ n).max())))
    out = dict(ncap=len(caps), cap_sizes=[c[2] for c in caps])
    if len(caps) != 2:
        return out
    (c1, n1, N1, pl1), (c2, n2, N2, pl2) = caps
    d = c2 - c1; L = float(np.linalg.norm(d))
    out.update(N=(N1, N2), planar=max(pl1, pl2), L=L, par=float(abs(n1 @ n2)))
    if L < 1e-6: return out
    a = d / L
    out['perp'] = float(min(abs(a @ n1), abs(a @ n2)))
    t = (U - c1) @ a
    rr = np.linalg.norm((U - c1) - np.outer(t, a), axis=1)
    r = float(np.median(rr))
    out.update(r=r, resid_r=float(np.abs(rr - r).max()), resid_t=float(np.minimum(np.abs(t), np.abs(t - L)).max()),
               c1=c1.tolist(), axis=a.tolist())
    return out

res = dict(job=job, pieces=[], summary=collections.Counter())
for sid, n_pl in sorted(placed.items()):
    p = pieces[sid]
    M, o = first[sid]
    T2.SPECIAL_NOTE = ''
    try:
        sh, k2 = T2.special_solid(job, sid, p, M, o)
    except Exception as e:
        sh, k2 = None, 'err ' + type(e).__name__
    note = T2.SPECIAL_NOTE
    if sh is not None and not note:
        res['summary']['rings_ok_pieces'] += 1; res['summary']['rings_ok_placed'] += n_pl
        continue
    if sh is None:
        res['summary']['special_none_pieces'] += 1; res['summary']['special_none_placed'] += n_pl
        cat = 'special_none'
    else:
        res['summary']['guess_pieces'] += 1; res['summary']['guess_placed'] += n_pl
        cat = 'guess'
    d = dict(sid=sid, name=p['name'], cat=cat, k2=k2, placed=n_pl, member_types=dict(mtypes[sid]),
             p={k: (round(v, 4) if isinstance(v, float) else v) for k, v in p.items()}, kind=kind(p), name_dia=name_dia(p['name']))
    fp = os.path.join(job, 'subm', str(sid))
    try:
        b = open(fp, 'rb').read()
    except OSError:
        d['file'] = 'missing'; res['pieces'].append(d); res['summary'][cat + '_nofile'] += n_pl; continue
    d['bytes'] = len(b)
    r = brep.parse(b)
    if r is None:
        d['brep'] = None
        V = T2.mesh_vertices(job, sid)
        if V is not None and len(V) >= 6:
            c = V.mean(0); u, s, vt = np.linalg.svd(V - c, full_matrices=False); a = vt[0]
            t = (V - c) @ a; rr = np.linalg.norm((V - c) - np.outer(t, a), axis=1)
            d['pca'] = dict(n=len(V), ptp_t=float(np.ptp(t)), r_med=float(np.median(rr)), r_min=float(rr.min()), r_max=float(rr.max()))
        res['summary'][cat + '_nobrep_placed'] += n_pl
        res['pieces'].append(d); continue
    V, F = r
    d['brep'] = dict(nv=len(V), nf=len(F), face_sizes=collections.Counter(len(f) for f in F).most_common(8))
    fit = straight_fit(V, F)
    d['fit'] = {k: (np.round(v, 5).tolist() if isinstance(v, (list, np.ndarray)) else (round(v, 5) if isinstance(v, float) else v)) for k, v in fit.items()}
    straight = (fit.get('ncap') == 2 and fit.get('resid_r', 9) < 2e-3 + 0.01 * fit.get('r', 0) and fit.get('resid_t', 9) < 2e-3
                and fit.get('perp', 0) > 0.9999 and fit.get('planar', 9) < 1e-3)
    d['straight'] = bool(straight)
    nd = d['name_dia']
    if straight:
        d['dia_vs_name'] = None if not nd else round(2 * fit['r'] / nd, 4)
        vol = np.pi * fit['r'] ** 2 * fit['L']
        d['cyl_ratio'] = round(vol * 0.2836 / p['wt'], 4) if p['wt'] > 0 else None
        res['summary'][cat + '_straight_placed'] += n_pl
    try:
        sh = brep.solid(V, F)
    except Exception:
        sh = None
    d['closed'] = sh is not None
    if sh is not None:
        from OCP.GProp import GProp_GProps
        from OCP.BRepGProp import BRepGProp
        g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g)
        d['brep_ratio'] = round(abs(g.Mass()) / 25.4 ** 3 * 0.2836 / p['wt'], 4) if p['wt'] > 0 else None
        if not straight:
            ok = d['brep_ratio'] is None or 0.6 < d['brep_ratio'] < 1.6
            res['summary'][cat + ('_bent_brep_ok_placed' if ok else '_bent_brep_badwt_placed')] += n_pl
    elif not straight:
        res['summary'][cat + '_bent_open_placed'] += n_pl
    if len([x for x in res['pieces'] if not x.get('straight')]) < 25 and not straight:
        used = sorted({i for f in F for i in f})
        d['V'] = np.round(V[used][:300], 5).tolist(); d['F'] = [list(map(int, f)) for f in F[:300]]
    res['pieces'].append(d)
res['summary'] = dict(res['summary'])
res['names'] = dict(collections.Counter(x['name'] for x in res['pieces']))
json.dump(res, open(outp, 'w'), default=lambda o: o.item() if hasattr(o, 'item') else str(o))
print(job, json.dumps(res['summary']))
