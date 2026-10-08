"""decided.py DIR.. : per engine, share of models whose every slotted group is decided (would lose hole_slotted_cut_round if enabled)"""
import json, glob, sys, collections
E = collections.defaultdict(collections.Counter); seen = set()
for d in sys.argv[1:]:
    for f in sorted(glob.glob(d + '/*.json')):
        k = f.split('/')[-1][:12]
        if k in seen: continue
        seen.add(k)
        try: j = json.load(open(f))
        except Exception: continue
        e = j.get('engine'); rows = j.get('rows', [])
        if not rows: E[e]['no_slotted_rows'] += 1; continue
        und = {r['g'] for r in rows if r['pred'] is None}; allg = {r['g'] for r in rows}
        E[e]['models'] += 1; E[e]['all_decided'] += (not und); E[e]['groups'] += len(allg); E[e]['groups_undecided'] += len(und)
for e in sorted(E, key=str): print(e, dict(E[e]))
