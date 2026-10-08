import json, glob, sys, collections
T = collections.defaultdict(collections.Counter); PM = collections.defaultdict(list); EXS = collections.defaultdict(list); ERR = collections.Counter()
for f in sorted(glob.glob(sys.argv[1] + '/*.json')):
    j = json.load(open(f)); e = j.get('engine')
    if j.get('err'): ERR[(e, j['err'][:40])] += 1; continue
    T[e]['models'] += 1
    mc = collections.Counter()
    for k, n in j.get('mesh_counts', []):
        T[e][tuple(k)] += n; mc[tuple(k)] += n
    if mc: PM[e].append((f.split('/')[-1][:12], j.get('guid_join'), dict(mc)))
    for r in j.get('mesh_rows', []):
        if len(EXS[(e, r['mk'])]) < 3: EXS[(e, r['mk'])].append({k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()})
    for k, n, ex in j.get('counts', []):
        if k[0] == 'control': T[e][('ctl',) + tuple(str(x) for x in k[1:])] += n
print('ERR', dict(ERR))
for e in sorted(T, key=str):
    print(e, sorted(T[e].items(), key=lambda kv: (-kv[1]))[:14])
    for x in PM[e][:12]: print('    ', x)
for k, v in sorted(EXS.items(), key=str): print('EX', k, v[:2])
