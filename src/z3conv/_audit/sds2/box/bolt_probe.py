#!/usr/bin/env python3
"""Do v5.3 bolt solids (SDS2 bolt records and nominal hole-stack bolts) sit on top of SDS2's own stored bolt hardware
pieces (BLT / washer / nut pieces written as exact B-rep)? Runs to_step2.convert on a job with two read-only probes
(placement and brep_placed wrappers) and compares positions.
usage: bolt_probe.py PIPE JOB OUT_STEP OUT_JSON"""
import sys, os, json, re, collections
import numpy as np
PIPE, job, out_step, out_json = sys.argv[1:5]
sys.path.insert(0, os.path.join(PIPE, 'decode'))
import to_step2
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

HW = re.compile(r'^(BLT|WS|TWS|NS|HN|NUT|WSH)')
hw = []      # (name, world centre in, local extent in)
bolts = []   # (src, head e, axis a, grip, d)
_bp = to_step2.brep_placed
_pl = to_step2.placement


def bbox_c(sh):
    b = Bnd_Box(); BRepBndLib.Add_s(sh, b)
    lo, hi = b.CornerMin(), b.CornerMax()
    c = np.array([(lo.X() + hi.X()) / 2, (lo.Y() + hi.Y()) / 2, (lo.Z() + hi.Z()) / 2]) / 25.4
    ext = np.array([hi.X() - lo.X(), hi.Y() - lo.Y(), hi.Z() - lo.Z()]) / 25.4
    return c, ext


def bp(job_, sid, p, M, o):
    r = _bp(job_, sid, p, M, o)
    try:
        if r is not None and HW.match(p.get('name', '')):
            if isinstance(r, tuple):
                _, local, trsf = r
                c, ext = bbox_c(local)
                w = np.asarray(o, float) + np.asarray(M, float).T @ c
            else:
                w, ext = bbox_c(r)
            hw.append((p['name'], w.tolist(), ext.tolist()))
    except Exception:
        pass
    return r


def pl(M, o):
    try:
        f = sys._getframe(1)
        if f.f_code.co_name == 'convert' and 'src' in f.f_locals and 'grip' in f.f_locals:
            L = f.f_locals
            bolts.append((L['src'], np.asarray(L['e'], float).tolist(), np.asarray(L['a'], float).tolist(), float(L['grip']), float(L['d'])))
    except Exception:
        pass
    return _pl(M, o)


to_step2.brep_placed = bp
to_step2.placement = pl
ok, _ = to_step2.convert(job, out_step, shared=True)
res = {'write_ok': bool(ok), 'hardware_pieces': len(hw), 'hardware_names': dict(collections.Counter(n.split()[0][:8] for n, _, _ in hw).most_common(12)),
       'bolts_by_src': dict(collections.Counter(b[0] for b in bolts))}
if hw and bolts:
    from scipy.spatial import cKDTree
    H = np.array([x[1] for x in hw]); tree = cKDTree(H)
    near = collections.Counter(); used = set(); samples = []
    for src, e, a, grip, d in bolts:
        e = np.array(e); a = np.array(a)
        mid = e + a * grip / 2
        cand = tree.query_ball_point(mid, grip / 2 + 3.0)
        hit = []
        for j in cand:
            v = H[j] - e; t = v @ a; perp = np.linalg.norm(v - t * a)
            if -2.5 <= t <= grip + 2.5 and perp <= max(0.75 * d, 0.5):
                hit.append(j)
        if hit:
            near[src] += 1; used.update(hit)
            if len(samples) < 12:
                samples.append({'src': src, 'head': [round(x, 3) for x in e], 'd': d, 'grip': grip,
                                'hardware_near': [hw[j][0] for j in hit[:4]]})
    res.update(bolts_with_hardware_on_axis=dict(near), hardware_pieces_on_some_bolt_axis=len(used), samples=samples)
json.dump(res, open(out_json, 'w'), indent=1)
print(json.dumps(res)[:3000])
