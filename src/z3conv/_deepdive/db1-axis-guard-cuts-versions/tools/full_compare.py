"""kit db1old vs patched db1old on every old-format DB1: per part O/E/x/y/L/profile/axis_ok/old_poly identity; lists every changed part."""
import sys, os, re, json, importlib.util, numpy as np
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(H, '..', 'kit_snapshot'))
from db1dec import load
def mod(path, name):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
A = mod(os.path.join(H, '..', 'kit_snapshot', 'db1old.py'), 'old_a')
B = mod(os.path.join(H, '..', 'patched', 'db1old.py'), 'old_b')
tot = dict(models=0, parts=0, same=0, changed=0)
for f in sys.argv[1:]:
    data = load(f)
    eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    if eng >= 7.5: continue
    Ma, ia, ca = A.read(data, eng); Mb, ib, cb = B.read(data, eng)
    da = {m['pid']: m for m in Ma}; dbb = {m['pid']: m for m in Mb}
    assert set(da) == set(dbb)
    ch = []
    for pid, a in da.items():
        b = dbb[pid]
        eq = all(np.allclose(a[k], b[k]) for k in ('O', 'E', 'x', 'xr', 'y')) and a['L'] == b['L'] and a['axis_ok'] == b['axis_ok'] \
             and a['prof'] == b['prof'] and a['old_poly'] == b['old_poly'] and a['cut'] == b['cut'] and a['bolt'] == b['bolt']
        if not eq:
            what = []
            if a['axis_ok'] != b['axis_ok']: what.append(f"axis_ok {a['axis_ok']}->{b['axis_ok']}")
            if a['old_poly'] != b['old_poly']: what.append('outline ' + ('all-zero->real' if all(all(c == 0 for c in p) for p in (a['old_poly'] or [(0,0,0)])) else 'changed'))
            if a['sgn'] != b['sgn']: what.append(f"sgn {a['sgn']}->{b['sgn']}")
            ch.append((pid, a['prof'], a['mat'], ', '.join(what)))
    tot['models'] += 1; tot['parts'] += len(da); tot['changed'] += len(ch); tot['same'] += len(da) - len(ch)
    print(os.path.basename(f)[:12], eng, 'parts', len(da), 'changed', len(ch), ch if ch else '', 'cut_rel equal', ca == cb, flush=True)
print('TOTAL', json.dumps(tot))
