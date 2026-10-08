"""Bolt matching without building solids: decoded holes of every placed piece (brep.holes, as brep_placed collects
them) -> hole stacks; SDS2 bolt records per member in the v4 frame vs the hole-validated frame; stacks covered by the
v4 rule (head within 0.002 in of a stack end) vs the patched rule (coaxial, overlapping plies).
usage: bolt_eval.py <patched decode dir> <job>"""
import sys, os, collections, numpy as np
sys.path.insert(0, sys.argv[1])
import brep, bolts as BR, to_step2 as T2
from piece_table import read_pieces, kind
from instances import material_instances
from sds2job import read_members
job = sys.argv[2]
P = read_pieces(job); mems, _ = read_members(job); mtype = {m.id: m.type for m in mems}
HC = {}
def holes(sid):
    if sid not in HC:
        try: HC[sid] = brep.holes(open(os.path.join(job, 'subm', str(sid)), 'rb').read())
        except Exception: HC[sid] = []
    return HC[sid]
hw = []; frames = {}; member_frames = {}
for n in sorted(mtype):
    if mtype[n] == 'Ref Point': continue
    try: main, inst = material_instances(job, n, P)
    except Exception: continue
    member_frames[n] = [(M, o) for _, M, o in inst]
    for sid, M, o in inst:
        if sid == main: frames[n] = (M, o); break
    for sid, M, o in inst:
        p = P.get(sid)
        if p is None: continue
        for h in holes(sid) or ():
            hw.append((o + M.T @ h["c"], -(M.T @ h["axis"]), h["depth"], h["bolt"], len(hw)))
print('placed holes', len(hw))
C, A, D, Tb, I = (np.array([h[i] for h in hw]) for i in range(5))
stacks = T2.bolt_stacks(C, A, D, Tb, I)
from scipy.spatial import cKDTree
_P = np.vstack([C, C + A * D[:, None]]); _P = _P[np.isfinite(_P).all(1) & (np.abs(_P).max(1) < 1e7)]
hole_faces = cKDTree(_P)
def dedup(recs):
    if not recs: return recs
    hp = np.array([r["head"] for r in recs]); drop = set()
    ok = np.isfinite(hp).all(1) & (np.abs(hp).max(1) < 1e7)
    idx = np.where(ok)[0]
    for i, j in sorted(cKDTree(hp[ok]).query_pairs(1e-3)):
        i, j = idx[i], idx[j]
        if i not in drop and abs(abs(recs[i]["axis"] @ recs[j]["axis"]) - 1) < 1e-3: drop.add(j)
    return [r for k, r in enumerate(recs) if k not in drop]
def f32filter(recs):
    if not any(r["layout"] == "f32" for r in recs): return recs, None
    on = {id(r): bool(np.isfinite(hole_faces.query(r["head"], distance_upper_bound=2e-3)[0])) if np.isfinite(r["head"]).all() and np.abs(r["head"]).max() < 1e7 else False for r in recs if r["layout"] == "f32"}
    rate = sum(on.values()) / max(len(on), 1)
    if rate < 0.35: recs = [r for r in recs if r["layout"] == "f64" or on[id(r)]]
    return recs, round(rate, 3)
def old_cov(recs):
    cov = set()
    ends = [(e, si) for si, (e, a, g, d) in enumerate(stacks)] + [(e + a * g, si) for si, (e, a, g, d) in enumerate(stacks)]
    tree = cKDTree(np.array([x for x, _ in ends]))
    for r in recs:
        if not (np.isfinite(r["head"]).all() and np.abs(r["head"]).max() < 1e7): continue
        dist, j = tree.query(r["head"], distance_upper_bound=2e-3)
        if np.isfinite(dist): cov.add(ends[j][1])
    return cov
st = {}
old = []; new = []
for n in sorted(mtype):
    try: old += BR.member_bolts(job, n, frames.get(n))
    except Exception: pass
    try: new += T2.bolts_in_best_frame(job, n, frames.get(n), member_frames.get(n, ()), hole_faces, st)
    except Exception as e: print('err', n, e)
old, r_old = f32filter(dedup(old)); new, r_new = f32filter(dedup(new))
co = old_cov(old) if old and stacks else set(); cn = T2.stacks_covered(stacks, new) if new and stacks else set()
print(os.path.basename(job), 'stacks', len(stacks))
print('  v5.1   : sds2 records', len(old), 'f32 on-hole rate', r_old, 'stacks covered', len(co), '-> nominal bolts', len(stacks) - len(co), 'total bolts', len(old) + len(stacks) - len(co))
print('  patched: sds2 records', len(new), 'f32 on-hole rate', r_new, 'stacks covered', len(cn), '-> nominal bolts', len(stacks) - len(cn), 'total bolts', len(new) + len(stacks) - len(cn), 'frames reselected', st.get('bolt_record_frames_reselected', 0))
# records on a hole face (sanity: placed where SDS2 drilled)
def onh(recs):
    H = np.array([r['head'] for r in recs]) if recs else np.zeros((0, 3)); ok = np.isfinite(H).all(1) & (np.abs(H).max(1) < 1e7) if len(H) else []
    return int(np.isfinite(hole_faces.query(H[ok], distance_upper_bound=0.25)[0]).sum()) if len(H) else 0
print('  record heads within 1/4 in of a decoded hole face: v5.1', onh(old), '/', len(old), ' patched', onh(new), '/', len(new))
