"""why_missing.py ID GID PID [GID PID ...]: Tekla says bolt group GID bolts part PID (type-10 relation) but the builder cut no hole:
bolt points + axis in the part's local frame (x = member axis from O, y, z = x cross y), part profile / section outline, and where the
bolt axis line crosses the part's extrusion slab."""
import sys, os, re, json
import numpy as np
W = os.path.dirname(os.path.abspath(__file__)); os.chdir(W)
sys.path.insert(0, os.path.join(W, 'kits', 'jfix'))
import db1old, db1bolts, db1step
from db1dec import load
i = [f[:-4] for f in os.listdir('src') if f.startswith(sys.argv[1])][0]
data = load(f'src/{i}.db1'); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng)
by = {m['pid']: m for m in M}
cat = json.load(open('kits/common/tekla_profiles.json'))
a = sys.argv[2:]
for g, p in zip(a[::2], a[1::2]):
    G = by[int(g)]; P = by[int(p)]
    kind, v, how = db1step.section_for(P['prof'], cat)
    print(f'== group {g} {G["prof"]} mat {G.get("mat")} pts {len(G.get("old_poly") or [])} | part {p} {P["prof"]} -> {kind} {v} ({how}) L={P["L"]:.1f} form={P.get("form")} poly={len(P.get("old_poly") or [])}')
    X = np.asarray(P['x'], float); Y = np.asarray(P['y'], float); Z = np.cross(X, Y); O = np.asarray(P['O'], float)
    R = np.stack([X, Y, Z], 1)
    for b in db1bolts.bolts_of(G)[:4]:
        c = R.T @ (np.asarray(b['c']) - O); ez = R.T @ np.asarray(b['ez'])
        # where does the bolt axis line cross the part's local planes y = 0 and z = 0
        s = []
        for k in (1, 2):
            if abs(ez[k]) > 1e-6:
                t = -c[k] / ez[k]; s.append((('y=0', 'z=0')[k - 1], [round(x, 1) for x in (c + ez * t)], round(t, 1)))
        print('   bolt c(local)', [round(x, 1) for x in c], 'axis(local)', [round(x, 3) for x in ez], 'L', b['L'], 'grip', b.get('grip'), '| crossings', s)
