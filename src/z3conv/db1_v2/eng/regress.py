import sys, pickle, subprocess, os, numpy as np
P = '/Users/dhiren/Downloads/Deccan/z3conv/db1_v2/_env/env/bin/python'
D = '/Users/dhiren/Downloads/Deccan/cad-db1-convert/pairs/data/'
tests = [(D + 'ag_7.64_606ed3d8.db1', '7.64'), (D + 's807.db1', '8.07'), (D + '7.82_4f7fa9df65.db1', '7.82'), (D + 'un_9.08_3089c30191.db1', '9.08'),
         (D + 'def_8.85_761416270c.db1', '8.85'), (D + 'def_8.53_dd6f8cfe9b.db1', '8.53'), (D + 'un_8.44_f57a7af8ea.db1', '8.44'), (D + 'nml_7.64_2e0d8bbeb5.db1', '7.64')]
os.makedirs('reg', exist_ok=True)
for f, eng in tests:
    nm = os.path.basename(f)
    for tag, src in (('before', '../re'), ('after', 'src')):
        out = f'reg/{nm}.{tag}.pkl'
        if not os.path.exists(out): subprocess.run([P, 'dump_members.py', src, f, eng, out], check=False)
    a = pickle.load(open(f'reg/{nm}.before.pkl', 'rb')); b = pickle.load(open(f'reg/{nm}.after.pkl', 'rb'))
    same = len(a['M']) == len(b['M']) and all(x[0] == y[0] and x[1] == y[1] and np.allclose(x[2], y[2]) and np.allclose(x[3], y[3]) and np.allclose(x[4], y[4]) and x[5] == y[5] for x, y in zip(a['M'], b['M']))
    sp = set(a['polys']) == set(b['polys']) and all((a['polys'][k] is None and b['polys'][k] is None) or (a['polys'][k] is not None and b['polys'][k] is not None and np.allclose(a['polys'][k], b['polys'][k])) for k in a['polys'])
    print(f'{nm:40s} {eng} members {len(a["M"])} -> {len(b["M"])} identical={same} plates={len(a["polys"])} identical={sp} lay_same={a["lay"] == b["lay"]}', flush=True)
