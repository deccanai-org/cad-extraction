#!/usr/bin/env python3
"""nestscan.py JOBDIR OUT.jsonl NMAX: piece files with a closed body whose bbox lies inside another body's bbox;
records the signed volume (source winding) of inner vs outer, and for same-sign (inner stored as solid) cases whether
the patched brep.solid() changes the volume (void / cut made against the source orientation)."""
import sys, os, json, random, importlib.util, numpy as np
W = '/work/agentwork/sds2-pieces-not-built-review/trees'
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
old = load('brep_old', W + '/v553/decode/brep.py'); new = load('brep_new', W + '/v553p/decode/brep.py')
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
def vol(s):
    if s is None: return None
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(s, g); return abs(g.Mass()) / 25.4 ** 3
def svol(V, faces):
    s = 0.0
    for f in faces:
        for l in old.loops_of(f)[:1]:
            P = V[l]
            for k in range(1, len(P) - 1): s += np.dot(P[0], np.cross(P[k], P[k + 1])) / 6.0
    return s
job, outp, nmax = sys.argv[1], sys.argv[2], int(sys.argv[3])
sub = os.path.join(job, 'subm'); fs = [f for f in os.listdir(sub) if f.isdigit()] if os.path.isdir(sub) else []
random.seed(11); random.shuffle(fs); fs = fs[:nmax]
fo = open(outp, 'w'); n2 = 0; nc = 0
for fn in fs:
    try: r = old.parse(open(os.path.join(sub, fn), 'rb').read())
    except Exception: r = None
    if r is None: continue
    V, F = r
    if len(F) > 4000: continue
    bs = old.bodies(F)
    if not 1 < len(bs) <= 64: continue
    n2 += 1
    info = []
    for b in bs:
        u = sorted({i for f in b for i in f}); U = V[u]
        info.append((U.min(0), U.max(0), svol(V, b), len(b)))
    pairs = []
    for j, (lo_j, hi_j, sj, nj) in enumerate(info):
        for i, (lo_i, hi_i, si, ni) in enumerate(info):
            if i != j and abs(si) > abs(sj) and np.all(lo_i <= lo_j + 1e-6) and np.all(hi_j <= hi_i + 1e-6):
                pairs.append((i, j, si, sj))
    if not pairs: continue
    nc += 1
    same = any(np.sign(si) == np.sign(sj) for i, j, si, sj in pairs)
    rec = dict(job=os.path.basename(job), piece=fn, nbodies=len(bs), pairs=[(i, j, round(si, 4), round(sj, 4)) for i, j, si, sj in pairs][:6], same_sign=bool(same))
    try:
        vo, vn = vol(old.solid(V, F)), vol(new.solid(V, F)); rec.update(vol_old=vo, vol_new=vn, changed=(vo is not None and vn is not None and abs(vo - vn) > 1e-6 * max(1, vo)))
    except Exception as e:
        rec['err'] = str(e)[:80]
    fo.write(json.dumps(rec) + '\n'); fo.flush()
fo.write(json.dumps(dict(job=os.path.basename(job), summary=dict(files=len(fs), multibody=n2, nested_bbox=nc))) + '\n'); fo.close()
