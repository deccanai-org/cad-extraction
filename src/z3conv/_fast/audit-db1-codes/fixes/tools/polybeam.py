"""polybeam.py ID..: form-4 part records with >= 3 polygon points: in which frame are the points (world offsets from O, or the
part csys xr / y / z), how long is the full path vs the written length L, how many are straight (collinear)."""
import sys, os, re, json, collections
import numpy as np
W = os.path.dirname(os.path.abspath(__file__)); os.chdir(W)
sys.path.insert(0, os.path.join(W, 'kits', 'jfix'))
import db1old
from db1dec import load
T = collections.Counter(); ratio = []
for a in sys.argv[1:]:
    i = [f[:-4] for f in os.listdir('src') if f.startswith(a)][0]
    data = load(f'src/{i}.db1'); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info, _ = db1old.read(data, eng)
    c = collections.Counter()
    for m in M:
        if m.get('cut') or m.get('bolt') or m.get('form') != 4: continue
        P = np.array([p for p in (m.get('old_poly') or [])], float)
        if len(P) < 3: continue
        s0 = P[1] - P[0]; n0 = np.linalg.norm(s0)
        if n0 < 1e-6: c['zero_first_seg'] += 1; continue
        d0 = s0 / n0
        xr, y = np.asarray(m['xr']), np.asarray(m['y']); z = np.cross(xr, y); x = np.asarray(m['x'])
        w_world = abs(d0 @ x)                                     # points = world offsets?
        dl = xr * d0[0] + y * d0[1] + z * d0[2]; w_local = abs(dl @ x)  # points in the part csys?
        seg = np.linalg.norm(np.diff(P, axis=0), axis=1); path = seg.sum()
        D = np.diff(P, axis=0); D = D[np.linalg.norm(D, axis=1) > 1e-6]; D = D / np.linalg.norm(D, axis=1)[:, None]
        straight = bool(np.all(np.abs(D @ D[0]) > 0.9999))
        c['n'] += 1; c['first_seg_eq_L'] += abs(n0 - m['L']) < 0.6; c['world_frame'] += w_world > 0.999; c['local_frame'] += w_local > 0.999
        c['straight'] += straight; c['path_gt_L+1'] += path > m['L'] + 1
        ratio.append(path / max(m['L'], 1e-6))
    print(i[:12], eng, dict(c))
    for k, v in c.items(): T[k] += v
r = np.array(ratio)
print('TOTAL', dict(T), 'path/L p50 p90 max', [round(float(np.percentile(r, q)), 2) for q in (50, 90)] + [round(float(r.max()), 1)] if len(r) else None)
