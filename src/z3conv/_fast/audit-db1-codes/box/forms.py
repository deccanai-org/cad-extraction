"""forms.py: old-engine part records by form (part_attr +8) and polygon point count; form 4 with >= 3 points = Tekla polybeam
(bent plate / folded member, points = the bent reference line), which the builder writes as ONE straight extrusion O -> O + x*L."""
import sys, os, re, json, collections, concurrent.futures as cf
import numpy as np
W = os.path.dirname(os.path.abspath(__file__)); os.chdir(W)
sys.path.insert(0, os.path.join(W, 'kits', 'jfix'))
ENG = json.load(open('state/engines.json'))


def one(i):
    import db1old
    from db1dec import load
    data = load(f'src/{i}.db1'); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info, _ = db1old.read(data, eng)
    c = collections.Counter(); ex = []
    for m in M:
        if m.get('cut') or m.get('bolt'): continue
        n = len(m.get('old_poly') or [])
        c[(m.get('form'), min(n, 4))] += 1
        if m.get('form') == 4 and n >= 3 and len(ex) < 3:
            P = np.array(m['old_poly']); seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
            ex.append({'pid': m['pid'], 'prof': m['prof'], 'L': round(m['L'], 1), 'pts': [[round(x, 1) for x in p] for p in m['old_poly']], 'path_len': round(float(seg.sum()), 1)})
    return i, eng, {f'{k[0]}:{k[1]}': v for k, v in c.items()}, ex


ids = [i for i, e in ENG.items() if e in ('6.87', '7.01', '7.24', '7.30')]
T = collections.Counter(); out = {}
with cf.ProcessPoolExecutor(4) as ex:
    for i, eng, c, e in ex.map(one, ids):
        out[i] = {'engine': eng, 'forms': c, 'polybeam_examples': e}
        for k, v in c.items(): T[k] += v
        T['models_with_polybeams'] += 1 if any(k.startswith('4:') and int(k.split(':')[1]) >= 3 for k in c) else 0
json.dump({'totals': dict(T), 'per_model': out}, open('report/forms.json', 'w'), indent=1)
print(dict(T))
for i, r in list(out.items())[:6]: print(i[:12], r['engine'], r['forms'], r['polybeam_examples'][:1])
