import json, glob, sys, collections
G = collections.defaultdict(dict); V = []
for f in sorted(glob.glob(sys.argv[1] + '/*.json')):
    j = json.load(open(f)); e = j.get('engine')
    for g, a in (j.get('gattr') or {}).items():
        if a.get('full'): G[(e, a['S'])][(f, g)] = bytes.fromhex(a['full'])
    for r in j.get('rows', []):
        if r['pred'] is not True or r['truth'] != ['slot']: continue
        pa = r['palong']; nd = set(r['ncdir'])
        if not (pa > 0.99 or pa < 0.01) or len(nd) != 1: continue
        V.append((e, f, str(r['g']), r.get('rank'), ('True' if pa > 0.99 else 'False') not in nd))
print('verdicts', collections.Counter((e, rot) for e, f, g, rk, rot in V))
for (e, S), recs in sorted(G.items()):
    n = len(recs); cands = []
    for k in range(S):
        vals = collections.Counter(b[k] for b in recs.values())
        nz = n - vals.get(0, 0)
        if vals.get(0, 0) and nz and set(vals) <= {0, 1, 2, 3} and nz / n < 0.6:
            cands.append((k, dict(vals)))
    print(e, 'S', S, 'groups', n, 'candidate bytes (0..3, sometimes nonzero):', cands[:20])
    # cross with verdicts
    for k, _ in cands[:20]:
        c = collections.Counter()
        for ee, f, g, rk, rot in V:
            b = recs.get((f, g))
            if b is None: continue
            c[(b[k], rk, rot)] += 1
        if c: print('    @%d (value, rank, nc_rotated):' % k, dict(c))
