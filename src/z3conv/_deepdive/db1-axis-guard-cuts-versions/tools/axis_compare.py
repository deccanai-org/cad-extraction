"""before/after of the point-table fix on db1old.read: dropped parts, per-part geometry identity for every other part."""
import sys, os, re, importlib.util, numpy as np
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(H, '..', 'kit_snapshot'))
from db1dec import load
def mod(path, name):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
A = mod(os.path.join(H, '..', 'kit_snapshot', 'db1old.py'), 'old_a')
B = mod(os.path.join(H, '..', 'patched', 'db1old.py'), 'old_b')
for f in sys.argv[1:]:
    data = load(f)
    eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    if eng >= 7.5: continue
    Ma, ia, ca = A.read(data, eng); Mb, ib, cb = B.read(data, eng)
    da = {m['pid']: m for m in Ma}; dbb = {m['pid']: m for m in Mb}
    changed = []; same = 0
    for pid, a in da.items():
        b = dbb[pid]
        eq = all(np.allclose(a[k], b[k]) for k in ('O', 'E', 'x', 'xr', 'y')) and a['L'] == b['L'] and a['axis_ok'] == b['axis_ok'] and a['prof'] == b['prof']
        if eq: same += 1
        else: changed.append((pid, a['prof'], a['axis_ok'], b['axis_ok'], a['sgn'], b['sgn']))
    print('==', os.path.basename(f)[:12], eng, 'parts', len(Ma), len(Mb), '| dropped before', sum(1 for m in Ma if m['axis_ok'] is False),
          'after', sum(1 for m in Mb if m['axis_ok'] is False), '| agreement', ia['axis_agreement'], '->', ib['axis_agreement'],
          '| identical parts', same, '| changed', changed)
