import sys, pickle, subprocess, os, numpy as np
P = '/Users/dhiren/Downloads/Deccan/z3conv/db1_v2/_env/env/bin/python'
D = '/Users/dhiren/Downloads/Deccan/cad-db1-convert/pairs/data/'
tests = [(D + 'ag_7.64_606ed3d8.db1', '7.64'), (D + 's807.db1', '8.07'), (D + '7.82_4f7fa9df65.db1', '7.82'), (D + 'un_9.08_3089c30191.db1', '9.08'),
         (D + 'def_8.85_761416270c.db1', '8.85'), (D + 'nml_7.64_2e0d8bbeb5.db1', '7.64'), (D + 'un_8.44_f57a7af8ea.db1', '8.44'),
         ('fit/p807_0.db1', '8.07'), ('fit/p807_1.db1', '8.07'), ('fit/p8.53.db1', '8.53'), ('fit/p8.85.db1', '8.85'), ('fit/p7.64.db1', '7.64'), ('fit/p9.08.db1', '9.08')]
os.makedirs('reg2', exist_ok=True)
for f, eng in tests:
    nm = os.path.basename(f)
    for tag, src in (('before', '../re'), ('after', 'src')):
        out = f'reg2/{nm}.{tag}.pkl'
        old = f'reg/{nm}.before.pkl'
        if tag == 'before' and os.path.exists(old) and not os.path.exists(out): os.link(old, out)
        if not os.path.exists(out): subprocess.run([P, 'dump_members.py', src, f, eng, out], check=False, stdout=subprocess.DEVNULL)
    a = pickle.load(open(f'reg2/{nm}.before.pkl', 'rb')); b = pickle.load(open(f'reg2/{nm}.after.pkl', 'rb'))
    same = len(a['M']) == len(b['M']) and all(x[0] == y[0] and x[1] == y[1] and np.allclose(x[2], y[2]) and np.allclose(x[3], y[3]) and np.allclose(x[4], y[4]) and x[5] == y[5] for x, y in zip(a['M'], b['M']))
    sp = set(a['polys']) == set(b['polys']) and all((a['polys'][k] is None and b['polys'][k] is None) or (a['polys'][k] is not None and b['polys'][k] is not None and np.allclose(a['polys'][k], b['polys'][k])) for k in a['polys'])
    la = {k: v for k, v in a['lay'].items()}; lb = {k: v for k, v in b['lay'].items()}
    print(f'{nm:32s} {eng} members {len(a["M"])} -> {len(b["M"])} identical={same} plates={len(a["polys"])} identical={sp} lay_same={la == lb}', flush=True)
