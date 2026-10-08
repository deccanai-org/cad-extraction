import json, glob, os, sys
A, B = sys.argv[1], sys.argv[2]
for f in sorted(glob.glob(f'{B}/*.json')):
    i = os.path.basename(f)
    if not os.path.exists(f'{A}/{i}'): continue
    a, b = json.load(open(f'{A}/{i}')), json.load(open(f))
    fa = (a.get('weights') or {}).get('by_family') or {}; fb = (b.get('weights') or {}).get('by_family') or {}
    ra = (a['weights']['step_lb'] or 0) / (a['weights']['sds2_lb'] or 1); rb = (b['weights']['step_lb'] or 0) / (b['weights']['sds2_lb'] or 1)
    print(f"===== {b['job'][:40]:40s} total {ra:.4f} -> {rb:.4f}  t {a.get('convert_s')} -> {b.get('convert_s')}  err={b.get('error')}")
    print('      skipped', a.get('skipped_by_reason'), '->', b.get('skipped_by_reason'), ' turned_brep', (b['weights'] or {}).get('turned_brep'))
    for k in sorted(set(fa) | set(fb), key=lambda k: -((fb.get(k) or fa.get(k) or {}).get('sds2_lb') or 0)):
        x, y = fa.get(k) or {}, fb.get(k) or {}
        if x.get('ratio') != y.get('ratio') or (x.get('ratio') and abs(x['ratio'] - 1) > 0.05):
            print(f"      {k:6s} n {x.get('n')}->{y.get('n')}  ratio {x.get('ratio')} -> {y.get('ratio')}   exact {(y.get('exact') or {}).get('ratio')}/{(y.get('exact') or {}).get('n')}  built {(y.get('built') or {}).get('ratio')}/{(y.get('built') or {}).get('n')}")
    print('      by_source', (b['weights'] or {}).get('by_source'))
