"""rotfind.py DIR : new-engine 'rotate slots' field search: per (engine, stride) score each byte offset of the bolt attribute record by
how well rule H (b==1 -> rotate even plies (k odd), b==2 -> rotate odd plies (k even)) predicts the NC rotated/not verdict"""
import json, glob, sys, collections
V = collections.defaultdict(list)
for f in sorted(glob.glob(sys.argv[1] + '/*.json')):
    j = json.load(open(f)); e = j.get('engine'); ga = j.get('gattr') or {}
    for r in j.get('rows', []):
        if r['pred'] is not True or r['truth'] != ['slot'] or r.get('plyrank') is None: continue
        pa = r['palong']; nd = set(r['ncdir'])
        if not (pa > 0.99 or pa < 0.01) or len(nd) != 1: continue
        a = ga.get(str(r['g']))
        if not a or not a.get('full'): continue
        V[(e, a['S'])].append((('True' if pa > 0.99 else 'False') not in nd, r['plyrank'], bytes.fromhex(a['full']), f.split('/')[-1][:12]))
for (e, S), L in sorted(V.items()):
    nrot = sum(1 for x in L if x[0])
    print(e, 'S', S, 'verdicts', len(L), 'rotated', nrot, 'models', len({x[3] for x in L}))
    sc = []
    for k in range(S):
        h = sum(1 for rot, kk, b, _ in L if rot == ((b[k] == 1 and kk % 2 == 1) or (b[k] == 2 and kk % 2 == 0)))
        nz = sum(1 for rot, kk, b, _ in L if rot == (b[k] != 0))
        sc.append((h, nz, k))
    sc.sort(reverse=True)
    print('   best H:', sc[:5]); print('   best nonzero:', sorted(sc, key=lambda t: -t[1])[:5])
    if sc[0][0] > 0:
        k = sc[0][2]; c = collections.Counter((b[k], kk, rot) for rot, kk, b, _ in L); print('   @%d (value, rank, rotated):' % k, dict(c))
