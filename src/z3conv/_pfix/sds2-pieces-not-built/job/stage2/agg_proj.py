#!/usr/bin/env python3
"""agg_proj.py PROJDIR ROWS.json OUT.json -> per model and per group: live skipped placements, projected outcome on v5.5.3
and on v5.5.3 + patch (sampled pieces scaled to the model's placements per reason)."""
import json, os, sys, glob, collections
pd, rows = sys.argv[1], {r['id']: r for r in json.load(open(sys.argv[2]))}
BUILT = lambda o: o and (o.startswith('built') or o.startswith('ref_'))
def cat(o):
    if o is None: return 'unsampled'
    if o.startswith('built_exact'): return 'built exact (SDS2 B-rep)'
    if o.startswith('built_approx_2g'): return 'built approx (profile, SDS2 weight outlier)'
    if o.startswith('built'): return 'built approx (stand-in)'
    if o == 'ref_solid': return 'reference closed solid'
    if o in ('ref_open_shell', 'ref_face_set'): return 'reference open surface (as stored)'
    if o.startswith('source_'): return 'tagged source_* (job lacks geometry)'
    if o == 'absurd': return 'still skipped (absurd)'
    if o.startswith('error'): return 'replay error'
    return 'still skipped: ' + o
models = []
G = {v: collections.Counter() for v in ('v553', 'v553q')}
Gm = {v: collections.Counter() for v in ('v553', 'v553q')}
for rid, r in rows.items():
    f553, f553q = os.path.join(pd, rid, 'v553.json'), os.path.join(pd, rid, 'v553q.json')
    if not (os.path.exists(f553) and os.path.exists(f553q)):
        models.append(dict(id=rid, conv=r['conv'], missing=True)); continue
    a, b = json.load(open(f553)), json.load(open(f553q))
    per = {}
    for V, d in (('v553', a), ('v553q', b)):
        tot = collections.Counter(); smp = collections.Counter(); out = collections.Counter()
        for x in d['pieces']:
            tot[x['reason']] += x['n']
            if x.get('sampled') and 'out' in x:
                smp[x['reason']] += x['n']; out[(x['reason'], cat(x['out']))] += x['n']
        res = collections.Counter()
        for (rs, c), n in out.items():
            res[c] += n * tot[rs] / max(smp[rs], 1)      # scale the sampled pieces to the reason's placements
        per[V] = dict(total=sum(tot.values()), by=dict(res))
        for c, n in res.items():
            G[V][c] += n
    live_total = per['v553']['total']
    def remaining(V, src_ok):
        return sum(n for c, n in per[V]['by'].items() if c.startswith('still') or c == 'replay error' or (c.startswith('tagged') and not src_ok))
    m = dict(id=rid, conv=r['conv'], version=r['version'], only=r['only'], job=a['job'], live_skipped=live_total,
             v553=per['v553']['by'], v553q=per['v553q']['by'],
             rem_v553=round(remaining('v553', False)), rem_v553q=round(remaining('v553q', False)),
             rem_v553q_srcok=round(remaining('v553q', True)))
    for V in ('v553', 'v553q'):
        Gm[V]['models with pieces still not built (converter)'] += remaining(V, False) > 0.5
    Gm['v553q']['models whose remaining skips are all source_* (grader patch)'] += (remaining('v553q', False) > 0.5 and remaining('v553q', True) < 0.5)
    models.append(m)
json.dump(dict(models=models, groups={k: dict(v) for k, v in G.items()}, model_counts={k: dict(v) for k, v in Gm.items()}),
          open(sys.argv[3], 'w'), indent=1)
print('models', len(models), 'with projection', sum(1 for m in models if not m.get('missing')))
for V in ('v553', 'v553q'):
    print(V, {k: round(v) for k, v in sorted(G[V].items(), key=lambda kv: -kv[1])})
    print('   ', dict(Gm[V]))
