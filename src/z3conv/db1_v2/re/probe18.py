import sys, numpy as np, collections
exec(open('probe17.py').read().split("st = collections.Counter(); ex = []")[0])
st = collections.Counter(); ex = []
for e, m in pairs:
    try: V = truthmesh.mesh(e)
    except Exception: st['mesh_fail'] += 1; continue
    dd = float(e.NominalDiameter or 20); P = positions(m)
    if P is None: st['no_positions'] += 1; continue
    okc, n, expl = truthmesh.check(V, m['O'], m['x'], m['y'], P, dd)
    good = okc == n and expl > 0.999
    st['exact' if good else 'off'] += 1; st['bolts'] += n; st['bolts_ok'] += okc
    if not good and len(ex) < 10: ex.append((m['prof'][:24], okc, n, round(expl, 3), np.round(np.array(P)[:4], 1).tolist()))
print(st)
for x in ex: print(x)
