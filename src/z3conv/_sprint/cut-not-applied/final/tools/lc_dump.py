"""lc_dump.py ID PID... : one part's frame, its P13 fitting / line-cut planes in the part frame and its type-11 cut parts"""
import sys, os, re, json, glob, numpy as np
W = '/work/agentwork/cut-not-applied'; ID = sys.argv[1]; KIT = os.environ.get('KIT', W + '/kitnp4')
sys.path.insert(0, KIT)
import db1old
from db1dec import load
np.set_printoptions(suppress=True, precision=3, linewidth=200)
src = glob.glob(f'{W}/src/{ID}*.db1')[0]; data = load(src); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng); byp = {m['pid']: m for m in M}; FIT = db1old.FIT
for pid in map(int, sys.argv[2:]):
    m = byp[pid]; x, y = m['x'], m['y']; z = np.cross(x, y); O = m['O']
    print('== part', pid, m['prof'], 'L %.2f' % m['L'], 'O', O, 'x', x, 'y', y, 'z', z, 'xr', m['xr'], 'sgn', m['sgn'], 'form', m.get('form'))
    for t in (9, 12):
        for P, n in FIT.get(t, {}).get(pid, []):
            Pl = np.array([(P - O) @ x, (P - O) @ y, (P - O) @ z]); nl = np.array([n @ x, n @ y, n @ z])
            print('   type', t, 'plane point (part frame u,v,w)', Pl, 'normal (part frame)', nl)
            # where does the plane cut the section rectangle [-60,60]^2 at the near end? solve u for corners
            for v_, w_ in ((0, 0), (50, 0), (0, 50), (-50, 0), (0, -50), (50, 50), (-50, -50)):
                if abs(nl[0]) > 1e-9:
                    u = Pl[0] - (nl[1] * (v_ - Pl[1]) + nl[2] * (w_ - Pl[2])) / nl[0]
                    print('        at (v,w)=(%d,%d) plane u = %.1f' % (v_, w_, u))
    for c in cut_rel.get(pid, []):
        cm = byp.get(c)
        if cm: print('   cut part', c, cm['prof'], 'L %.1f' % cm['L'], 'O(part frame)', np.array([(cm['O'] - O) @ x, (cm['O'] - O) @ y, (cm['O'] - O) @ z]), 'x(part frame)', np.array([cm['x'] @ x, cm['x'] @ y, cm['x'] @ z]), 'npoly', len(cm.get('old_poly') or []))
