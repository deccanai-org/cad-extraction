"""agg.py OUTDIR [SEL.json]: per engine agreement of the decoded slot ply selection (+ slot direction) with Tekla NC truth"""
import json, glob, os, sys, collections
E = collections.defaultdict(collections.Counter); PM = collections.defaultdict(list); BAD = collections.defaultdict(list)
for f in sorted(glob.glob(os.path.join(sys.argv[1], '*.json'))):
    try: j = json.load(open(f))
    except Exception: continue
    e = j.get('engine') or '?'; c = collections.Counter()
    E[e]['models'] += 1
    for r in j.get('rows', []):
        t = r['truth']
        c['parts'] += 1
        if len(t) != 1 or t[0] not in ('slot', 'round'):
            c['no_truth' if not t else 'truth_ambiguous'] += 1; continue
        ts = t[0] == 'slot'
        if r['pred'] is None: c['truth_but_undecided'] += 1; c['und_' + t[0]] += 1; continue
        c['n'] += 1; ok = r['pred'] == ts; c['agree' if ok else 'disagree'] += 1
        if not ok and len(BAD[e]) < 12: BAD[e].append((os.path.basename(f)[:12], r['g'], r['pid'], r['prof'], r['n'], r['mask'], r['pred'], t))
        if ts and r['pred']:
            pa = r['palong']; nd = set(r['ncdir'])
            if pa > 0.99 or pa < 0.01:
                want = 'True' if pa > 0.99 else 'False'
                if nd == {want}: c['dir_ok'] += 1
                elif nd and want not in nd: c['dir_rot90'] += 1
                else: c['dir_mixed'] += 1
            else: c['dir_oblique'] += 1
    for k, v in c.items(): E[e][k] += v
    if c['n']: PM[e].append((os.path.basename(f)[:12], c['n'], c['agree'], c.get('dir_ok', 0), c.get('dir_rot90', 0)))
for e in sorted(E):
    c = E[e]; n = c['n']
    print(e, dict(c), 'agree %.4f' % (c['agree'] / n) if n else '', 'models_with_truth', len(PM[e]))
    print('   per model (sha, n, agree, dir_ok, dir_rot90):', PM[e][:30])
    if BAD[e]: print('   disagreements:', BAD[e])
