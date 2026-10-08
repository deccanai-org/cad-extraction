"""For every axis-guard-dropped part: reference points, csys, the agreement metric, and nearby 'twin' parts with the same profile."""
import sys, os, re, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'kit_snapshot'))
import db1old
from db1dec import load
for f in sys.argv[1:]:
    data = load(f)
    eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    o = db1old.Old(data); I = o.I_all; D = o.D_all
    P = db1old.PART_NEW if eng >= 7.1 else db1old.PART_OLD
    # rebuild point table exactly as db1old
    N = len(I) - 400
    pv = np.zeros(N, bool)
    pv[:N - 32] = (I[:N - 32] > 0) & (I[4:N - 28] >= 0) & (I[4:N - 28] <= 64)
    for k in (8, 16, 24):
        v = D[k:N - 32 + k]; pv[:N - 32] &= np.isfinite(v) & (np.abs(v) < 1e8)
    pts_off = o.runs(pv, 33)
    pts = {}; dup = {}
    for q in pts_off:
        pid = int(I[q]); p = np.array([D[q + 8], D[q + 16], D[q + 24]])
        if pid in pts and not np.allclose(pts[pid], p): dup.setdefault(pid, [pts[pid]]).append(p)
        pts[pid] = p
    M, info, cut_rel = db1old.read(data, eng)
    print('==', os.path.basename(f)[:12], 'eng', eng, 'points with conflicting duplicates:', len(dup))
    for m in [m for m in M if m.get('axis_ok') is False]:
        q = m['off']; p1id, p2id = int(I[q + P['p1']]), int(I[q + P['p2']])
        p1, p2 = pts[p1id], pts[p2id]; d = p2 - p1; dl = np.linalg.norm(d)
        Lr = d @ m['xr']
        print(f"  pid {m['pid']} {m['prof']} L={m['L']:.1f} |p2-p1|={dl:.1f} cos={abs(Lr)/dl:.4f} angle={np.degrees(np.arccos(min(1,abs(Lr)/dl))):.1f}deg")
        print('    p1', np.round(p1, 1), 'p2', np.round(p2, 1), 'd', np.round(d, 1), 'O', np.round(m['O'], 1), 'E', np.round(m['E'], 1))
        print('    xr', np.round(m['xr'], 4), 'y', np.round(m['y'], 4), 'p1 dup?', p1id in dup, 'p2 dup?', p2id in dup)
        # O relative to p1/p2
        print('    O-p1', np.round(m['O'] - p1, 1), 'O-p2', np.round(m['O'] - p2, 1))
        # twins: same profile, same L
        tw = [t for t in M if t['prof'] == m['prof'] and abs(t['L'] - m['L']) < 1 and t is not m]
        print('    twins same prof+L:', len(tw), [(t['pid'], t['axis_ok'], np.round(t['xr'], 3).tolist(), np.round(t['y'], 3).tolist()) for t in tw[:4]])
