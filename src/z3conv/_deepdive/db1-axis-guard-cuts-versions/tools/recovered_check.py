"""Recovered parts: with the clean points, |p2-p1| vs stored length L, O's offset from the reference line (Tekla 'position' offsets),
and the offsets of same-profile parts that always passed (consistency)."""
import sys, os, re, importlib.util, numpy as np
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(H, '..', 'kit_snapshot'))
from db1dec import load
def mod(path, name):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
A = mod(os.path.join(H, '..', 'kit_snapshot', 'db1old.py'), 'old_a')
B = mod(os.path.join(H, '..', 'patched', 'db1old.py'), 'old_b')
def refpts(mod_, data, eng, m):
    # re-read the part's p1/p2 via the module's own point table (monkeypatch-free: rebuild like read())
    return None
for f in sys.argv[1:]:
    data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    Ma, _, _ = A.read(data, eng); Mb, _, _ = B.read(data, eng)
    bad = {m['pid'] for m in Ma if m['axis_ok'] is False}
    o = B.Old(data); I = o.I_all; D = o.D_all; P = B.PART_NEW if eng >= 7.1 else B.PART_OLD
    # clean point lookup
    N = len(I) - 400
    pv = np.zeros(N, bool); pv[:N - 32] = (I[:N - 32] > 0) & (I[4:N - 28] >= 0) & (I[4:N - 28] <= 64)
    for k in (8, 16, 24):
        v = D[k:N - 32 + k]; pv[:N - 32] &= np.isfinite(v) & (np.abs(v) < 1e8)
    pts = {}
    for q in o.runs(pv, 33):
        q = int(q)
        if all(D[q + k] == 0 or abs(D[q + k]) > 1e-100 for k in (8, 16, 24)): pts.setdefault(int(I[q]), np.array([D[q+8], D[q+16], D[q+24]]))
    def info(m):
        q = m['off']; p1 = pts[int(I[q + P['p1']])]; p2 = pts[int(I[q + P['p2']])]
        d = p2 - p1; dl = np.linalg.norm(d); u = d / dl
        off = m['O'] - p1; along = off @ u; perp = off - along * u
        # perp offset in part frame (y, z)
        z = np.cross(m['xr'], m['y'])
        return dl, along, (round(float(perp @ m['y']), 1), round(float(perp @ z), 1))
    print('==', os.path.basename(f)[:12])
    for m in Mb:
        if m['pid'] not in bad: continue
        dl, along, pz = info(m)
        tw = [t for t in Mb if t['prof'] == m['prof'] and t['pid'] not in bad and not t['cut']]
        offs = {}
        for t in tw:
            try:
                a = info(t); offs[a[2]] = offs.get(a[2], 0) + 1
            except KeyError: pass
        print(f"  pid {m['pid']} {m['prof']}: L={m['L']:.1f} |p2-p1|={dl:.1f} O-along={along:.1f} O-perp(y,z)={pz} | same-profile parts' perp offsets: {sorted(offs.items(), key=lambda x:-x[1])[:4]}")
