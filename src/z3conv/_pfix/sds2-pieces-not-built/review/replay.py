#!/usr/bin/env python3
"""replay.py JOBDIR OUT.jsonl NMAX : piece-level replay of brep.solid / brep.shell, v5.5.3 vs v5.5.3+patch, on the
job's own piece files. Flags: solid lost, volume changed, invalid, area of a newly closed solid != area of the source's
own kept faces (would mean faces added), nested-void orientation in the source mesh."""
import sys, os, json, random, time, importlib.util, collections
import numpy as np
W = '/work/agentwork/sds2-pieces-not-built-review/trees'
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
old = load('brep_old', W + '/v553/decode/brep.py'); new = load('brep_new', W + '/v553p/decode/brep.py')
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE
MM = 25.4

def props(s):
    if s is None: return None
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(s, g); v = abs(g.Mass()) / MM ** 3
    g2 = GProp_GProps(); BRepGProp.SurfaceProperties_s(s, g2); a = g2.Mass() / MM ** 2
    cnt = lambda t: (lambda ex: sum(1 for _ in iter(lambda: (ex.More() and (ex.Next() or True)), False)))(TopExp_Explorer(s, t))
    ns = 0; ex = TopExp_Explorer(s, TopAbs_SOLID)
    while ex.More(): ns += 1; ex.Next()
    nsh = 0; ex = TopExp_Explorer(s, TopAbs_SHELL)
    while ex.More(): nsh += 1; ex.Next()
    nf = 0; ex = TopExp_Explorer(s, TopAbs_FACE)
    while ex.More(): nf += 1; ex.Next()
    return dict(vol=v, area=a, nsol=ns, nshell=nsh, nface=nf, valid=bool(BRepCheck_Analyzer(s).IsValid()))

def face_area(V, f):
    ls = old.loops_of(f)
    if not ls: return 0.0
    ar = sorted((old._area(V[l]) for l in ls), reverse=True)
    return ar[0] - sum(ar[1:])

def signed_vol(V, faces):
    s = 0.0
    for f in faces:
        for l in old.loops_of(f)[:1]:
            P = V[l]
            for k in range(1, len(P) - 1):
                s += np.dot(P[0], np.cross(P[k], P[k + 1])) / 6.0
    return s

job, outp, nmax = sys.argv[1], sys.argv[2], int(sys.argv[3])
sub = os.path.join(job, 'subm')
files = sorted(os.listdir(sub), key=lambda x: (len(x), x)) if os.path.isdir(sub) else []
random.seed(7); random.shuffle(files)
if len(sys.argv) > 4:
    want = [l.strip() for l in open(sys.argv[4]) if l.strip()]
    have = set(files); files = [w for w in want if w in have]
    random.shuffle(files)
files = files[:nmax]
fo = open(outp, 'w'); C = collections.Counter(); t0 = time.time()
for fn in files:
    try:
        b = open(os.path.join(sub, fn), 'rb').read()
    except Exception:
        continue
    r = old.parse(b); r3 = None
    if r is None:
        r3 = new.parse(b, *new.LAYOUTS[0], nvmin=3)
        C['parse_none'] += 1
        if r3 is not None:
            V3, F3 = r3; ext = np.ptp(V3[sorted({i for f in F3 for i in f})], 0).tolist()
            fo.write(json.dumps(dict(job=os.path.basename(job), piece=fn, kind='nvmin3', bytes=len(b), nv=len(V3), nf=len(F3), ext=ext,
                                     absmax=float(np.abs(V3).max()))) + '\n'); C['nvmin3'] += 1
        continue
    V, F = r
    if len(F) > 4000:
        C['skip_big'] += 1; continue
    t1 = time.time()
    try: so = old.solid(V, F)
    except Exception: so = None
    t2 = time.time()
    try: sn = new.solid(V, F)
    except Exception: sn = None
    t3 = time.time()
    po, pn = props(so), props(sn)
    rec = dict(job=os.path.basename(job), piece=fn, nf=len(F), t_old=round(t2 - t1, 3), t_new=round(t3 - t2, 3))
    flag = None
    if po and not pn: flag = 'LOST'
    elif pn and not po: flag = 'NEW'
    elif po and pn:
        if abs(po['vol'] - pn['vol']) > 1e-6 * max(1.0, po['vol']) or po['nsol'] != pn['nsol']: flag = 'CHANGED'
    if pn and not pn['valid']: flag = (flag or '') + '+INVALID'
    if flag:
        rec.update(flag=flag, old=po, new=pn)
        try:
            Fc, ndeg, ndup = new.clean_faces(V, F)
            rec.update(ndeg=ndeg, ndup=ndup, src_area_all=sum(face_area(V, f) for f in F), src_area_kept=sum(face_area(V, f) for f in Fc))
            if pn:
                rec['area_ratio_vs_kept'] = pn['area'] / max(1e-12, rec['src_area_kept'])
            if 'CHANGED' in flag:
                bs = old.bodies(F)
                rec['bodies'] = [dict(nf=len(p), svol=signed_vol(V, p)) for p in bs][:20]
        except Exception as e:
            rec['err'] = str(e)[:100]
        fo.write(json.dumps(rec) + '\n'); fo.flush()
    C[flag or ('both_none' if not po and not pn else 'same')] += 1
    C['t_old'] += t2 - t1; C['t_new'] += t3 - t2
fo.write(json.dumps(dict(job=os.path.basename(job), summary=dict(C), n=len(files), sec=round(time.time() - t0, 1))) + '\n'); fo.close()
